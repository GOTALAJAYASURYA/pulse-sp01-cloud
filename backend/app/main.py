import os
import json
import asyncio
from datetime import datetime, timezone
import uuid
import redis.asyncio as aioredis
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.core.database import SessionLocal, engine, Base
from app.mqtt.worker import start_mqtt_worker
from app.simulator_runner import start_cloud_simulator
from app.models.models import Ward, Bed, Device, Patient, Admission, DeviceAssociation, MultiDeviceTelemetryLog, DiagnosticReport

Base.metadata.create_all(bind=engine)

def run_db_migrations():
    """Auto-migrate schema and create new tables/columns safely."""
    try:
        with engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS devices (
                    device_id VARCHAR(64) PRIMARY KEY,
                    device_type VARCHAR(30) NOT NULL,
                    model_name VARCHAR(50) DEFAULT 'Pulse Pro Series',
                    firmware_version VARCHAR(30) DEFAULT 'v2.1.0',
                    status VARCHAR(30) DEFAULT 'AVAILABLE',
                    last_heartbeat TIMESTAMP WITH TIME ZONE
                );

                ALTER TABLE patients ADD COLUMN IF NOT EXISTS age INTEGER;
                ALTER TABLE patients ADD COLUMN IF NOT EXISTS gender VARCHAR(20) DEFAULT 'Male';
                ALTER TABLE patients ADD COLUMN IF NOT EXISTS blood_group VARCHAR(10) DEFAULT 'O+';
                ALTER TABLE patients ADD COLUMN IF NOT EXISTS phone_number VARCHAR(25);
                ALTER TABLE patients ADD COLUMN IF NOT EXISTS address TEXT;

                ALTER TABLE admissions ADD COLUMN IF NOT EXISTS admission_type VARCHAR(50) DEFAULT 'Emergency';
                ALTER TABLE admissions ADD COLUMN IF NOT EXISTS attending_doctor VARCHAR(100) DEFAULT 'Duty Medical Officer';
                ALTER TABLE admissions ADD COLUMN IF NOT EXISTS discharge_type VARCHAR(50);
                ALTER TABLE admissions ADD COLUMN IF NOT EXISTS discharged_at TIMESTAMP WITH TIME ZONE;

                ALTER TABLE device_associations ADD COLUMN IF NOT EXISTS device_type VARCHAR(30) DEFAULT 'SYRINGE_PUMP';

                CREATE TABLE IF NOT EXISTS multi_device_telemetry_logs (
                    recorded_at TIMESTAMP WITH TIME ZONE NOT NULL,
                    device_id VARCHAR(64) NOT NULL,
                    device_type VARCHAR(30) NOT NULL,
                    telemetry_data JSON NOT NULL,
                    PRIMARY KEY (recorded_at, device_id)
                );
            """))
            print("[✓] Multi-device schema migrations applied.")
    except Exception as e:
        print(f"[!] Migration notice: {e}")

app = FastAPI(title="Pulse Enterprise Multi-Device Telemetry Suite")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.on_event("startup")
def startup_event():
    run_db_migrations()
    start_mqtt_worker()
    start_cloud_simulator()

# --- Request Schemas ---
class PatientAdmissionRequest(BaseModel):
    bed_number: str
    patient_mrn: str
    patient_name: str
    age: Optional[int] = 45
    gender: Optional[str] = "Male"
    blood_group: Optional[str] = "O+"
    phone_number: Optional[str] = ""
    address: Optional[str] = ""
    admission_type: Optional[str] = "Emergency"
    attending_doctor: Optional[str] = "Dr. Robert Vance"
    primary_diagnosis: Optional[str] = "Acute Clinical Stabilization"

class AttachDeviceRequest(BaseModel):
    bed_number: str
    patient_mrn: str
    admission_id: Optional[str] = None
    device_id: str
    device_type: str  # 'PATIENT_MONITOR', 'SYRINGE_PUMP', 'DIALYSIS'

class UnbindDeviceRequest(BaseModel):
    device_id: str

class DischargeEncounterRequest(BaseModel):
    bed_number: str
    patient_mrn: str
    discharge_type: Optional[str] = "Routine / Recovered"

class ReportAttachRequest(BaseModel):
    patient_mrn: str
    department: str
    test_name: str
    parameters: dict
    technician_notes: str = ""
    technician_name: str = "Diagnostic Staff"


# --- REST Endpoints ---

@app.get("/")
def health_check():
    return {"status": "online", "system": "Pulse Multi-Device Central Telemetry"}

@app.get("/api/v1/registry-status")
def get_registry_status(db: Session = Depends(get_db)):
    """Fetch all active bed encounters with their attached multi-device bays."""
    try:
        active_admissions = (
            db.query(Admission)
            .filter(Admission.status == "ADMITTED")
            .order_by(Admission.admitted_at.desc())
            .all()
        )

        beds_list = []
        busy_bed_numbers = set()

        for adm in active_admissions:
            patient = db.query(Patient).filter(Patient.patient_id == adm.patient_id).first()
            bed = db.query(Bed).filter(Bed.bed_id == adm.bed_id).first()
            bed_no = bed.bed_number if bed else adm.bed_id
            busy_bed_numbers.add(bed_no)

            # Query all active devices attached to this encounter
            active_dev_assocs = (
                db.query(DeviceAssociation)
                .filter(
                    DeviceAssociation.admission_id == adm.admission_id,
                    DeviceAssociation.unpaired_at.is_(None)
                )
                .all()
            )

            attached_devices = [
                {
                    "association_id": str(da.association_id),
                    "device_id": da.device_id,
                    "device_type": da.device_type,
                    "paired_at": da.paired_at.isoformat() if da.paired_at else None
                }
                for da in active_dev_assocs
            ]

            beds_list.append({
                "bed_id": bed.bed_id if bed else bed_no,
                "bed_number": bed_no,
                "admission_id": str(adm.admission_id),
                "patient_mrn": patient.patient_id if patient else adm.patient_id,
                "patient_name": f"{patient.first_name} {patient.last_name}".strip() if patient else "Patient",
                "age": patient.age if patient else 45,
                "gender": patient.gender if patient else "Male",
                "blood_group": patient.blood_group if patient else "O+",
                "admission_type": adm.admission_type,
                "attending_doctor": adm.attending_doctor,
                "admitted_at": adm.admitted_at.isoformat() if adm.admitted_at else None,
                "devices": attached_devices
            })

        # Suggest next bed & MRN
        all_beds = [b.bed_number for b in db.query(Bed).all()]
        free_beds = sorted([b for b in all_beds if b not in busy_bed_numbers])
        if free_beds:
            next_bed = free_beds[0]
        else:
            idx = 1
            while f"ICU-B{idx}" in busy_bed_numbers:
                idx += 1
            next_bed = f"ICU-B{idx}"

        total_patients = db.query(Patient).count()
        next_mrn = f"PTN-{str(total_patients + 1).zfill(6)}"

        return {
            "active_associations": beds_list,
            "next_suggestions": {
                "bed": next_bed,
                "mrn": next_mrn
            }
        }
    except Exception as e:
        print(f"[!] Registry status error: {e}")
        return {"active_associations": [], "next_suggestions": {"bed": "ICU-B1", "mrn": "PTN-000001"}}

@app.post("/api/v1/admit-patient")
def admit_patient(req: PatientAdmissionRequest, db: Session = Depends(get_db)):
    """Admit patient to an ICU Bed with 0 attached devices initially."""
    try:
        now = datetime.now(timezone.utc)

        # 1. Ward
        ward = db.query(Ward).filter(Ward.ward_id == "icu-ward-a").first()
        if not ward:
            ward = Ward(ward_id="icu-ward-a", name="Main ICU Wing", ward_type="ICU")
            db.add(ward)
            db.flush()

        # 2. Bed
        bed = db.query(Bed).filter((Bed.bed_id == req.bed_number) | (Bed.bed_number == req.bed_number)).first()
        if not bed:
            bed = Bed(bed_id=req.bed_number, ward_id="icu-ward-a", bed_number=req.bed_number, current_status="OCCUPIED")
            db.add(bed)
            db.flush()
        else:
            bed.current_status = "OCCUPIED"

        # 3. Patient
        name_parts = req.patient_name.strip().split(" ", 1)
        first_name = name_parts[0] if name_parts[0] else "Patient"
        last_name = name_parts[1] if len(name_parts) > 1 else ""

        patient = db.query(Patient).filter(Patient.patient_id == req.patient_mrn).first()
        if not patient:
            patient = Patient(
                patient_id=req.patient_mrn,
                first_name=first_name,
                last_name=last_name,
                age=req.age,
                gender=req.gender,
                blood_group=req.blood_group,
                phone_number=req.phone_number,
                address=req.address
            )
            db.add(patient)
            db.flush()

        # 4. Admission
        adm = Admission(
            admission_id=uuid.uuid4(),
            patient_id=patient.patient_id,
            bed_id=bed.bed_id,
            primary_diagnosis=req.primary_diagnosis or "Acute Clinical Stabilization",
            admission_type=req.admission_type or "Emergency",
            attending_doctor=req.attending_doctor or "Dr. Robert Vance",
            admitted_at=now,
            status="ADMITTED"
        )
        db.add(adm)
        db.commit()

        return {"status": "success", "admission_id": str(adm.admission_id), "bed_number": req.bed_number}
    except Exception as e:
        db.rollback()
        return {"status": "error", "message": str(e)}

@app.post("/api/v1/devices/attach")
def attach_device_to_bed(req: AttachDeviceRequest, db: Session = Depends(get_db)):
    """Dynamically attach a PM, SP, or Dialysis device to an active patient encounter."""
    try:
        now = datetime.now(timezone.utc)

        # 1. Guardrail: Device must not be active elsewhere
        existing_assoc = db.query(DeviceAssociation).filter(
            DeviceAssociation.device_id == req.device_id,
            DeviceAssociation.unpaired_at.is_(None)
        ).first()

        if existing_assoc:
            raise HTTPException(status_code=400, detail=f"Device {req.device_id} is currently attached to another bed!")

        # 2. Get or create Device record
        device = db.query(Device).filter(Device.device_id == req.device_id).first()
        if not device:
            device = Device(
                device_id=req.device_id,
                device_type=req.device_type,
                status="IN_USE",
                last_heartbeat=now
            )
            db.add(device)
            db.flush()
        else:
            device.status = "IN_USE"

        # 3. Resolve active admission
        admission = None
        if req.admission_id:
            admission = db.query(Admission).filter(Admission.admission_id == req.admission_id).first()
        if not admission:
            admission = db.query(Admission).filter(
                Admission.patient_id == req.patient_mrn,
                Admission.status == "ADMITTED"
            ).first()

        if not admission:
            raise HTTPException(status_code=404, detail="No active admission found for this bed/patient.")

        # 4. Create Association
        assoc = DeviceAssociation(
            association_id=uuid.uuid4(),
            admission_id=admission.admission_id,
            bed_id=req.bed_number,
            device_id=device.device_id,
            device_type=req.device_type,
            paired_at=now
        )
        db.add(assoc)
        db.commit()

        return {"status": "success", "device_id": req.device_id, "device_type": req.device_type}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        return {"status": "error", "message": str(e)}

@app.post("/api/v1/devices/unbind")
def unbind_single_device(req: UnbindDeviceRequest, db: Session = Depends(get_db)):
    """Unbind a specific device from a bed without discharging the patient."""
    try:
        now = datetime.now(timezone.utc)
        assoc = db.query(DeviceAssociation).filter(
            DeviceAssociation.device_id == req.device_id,
            DeviceAssociation.unpaired_at.is_(None)
        ).first()

        if assoc:
            assoc.unpaired_at = now
            device = db.query(Device).filter(Device.device_id == req.device_id).first()
            if device:
                device.status = "AVAILABLE"
            db.commit()
            return {"status": "success", "message": f"Device {req.device_id} released."}

        return {"status": "error", "message": "Active association not found for device."}
    except Exception as e:
        db.rollback()
        return {"status": "error", "message": str(e)}

@app.post("/api/v1/discharge-encounter")
def discharge_patient_encounter(req: DischargeEncounterRequest, db: Session = Depends(get_db)):
    """Discharge patient and unbind all currently attached equipment in one step."""
    try:
        now = datetime.now(timezone.utc)

        admission = db.query(Admission).filter(
            Admission.patient_id == req.patient_mrn,
            Admission.status == "ADMITTED"
        ).first()

        if admission:
            admission.status = "DISCHARGED"
            admission.discharged_at = now
            admission.discharge_type = req.discharge_type

            # Unbind all attached devices
            active_assocs = db.query(DeviceAssociation).filter(
                DeviceAssociation.admission_id == admission.admission_id,
                DeviceAssociation.unpaired_at.is_(None)
            ).all()

            for a in active_assocs:
                a.unpaired_at = now
                dev = db.query(Device).filter(Device.device_id == a.device_id).first()
                if dev:
                    dev.status = "AVAILABLE"

            bed = db.query(Bed).filter((Bed.bed_id == req.bed_number) | (Bed.bed_number == req.bed_number)).first()
            if bed:
                bed.current_status = "AVAILABLE"

            db.commit()
            return {"status": "success", "message": f"Patient {req.patient_mrn} discharged and all hardware released."}

        return {"status": "error", "message": "No active admission found to discharge."}
    except Exception as e:
        db.rollback()
        return {"status": "error", "message": str(e)}

@app.post("/api/v1/reports/attach")
def attach_diagnostic_report(req: ReportAttachRequest, db: Session = Depends(get_db)):
    """Attach blood/scan investigations to the active patient encounter."""
    try:
        patient = db.query(Patient).filter(Patient.patient_id == req.patient_mrn).first()
        if not patient:
            raise HTTPException(status_code=404, detail=f"Patient {req.patient_mrn} not found.")

        active_adm = db.query(Admission).filter(
            Admission.patient_id == patient.patient_id,
            Admission.status == "ADMITTED"
        ).first()

        report = DiagnosticReport(
            report_id=uuid.uuid4(),
            patient_id=patient.patient_id,
            admission_id=active_adm.admission_id if active_adm else None,
            department=req.department.upper(),
            test_name=req.test_name,
            parameters=req.parameters,
            technician_notes=req.technician_notes,
            technician_name=req.technician_name,
            created_at=datetime.now(timezone.utc)
        )
        db.add(report)
        db.commit()
        return {"status": "success", "report_id": str(report.report_id)}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        return {"status": "error", "message": str(e)}

@app.get("/api/v1/patient-dossier/{patient_id}")
def get_patient_dossier(patient_id: str, db: Session = Depends(get_db)):
    """Encounter dossier with patient demographics, reports, and attached hardware delivery metrics."""
    try:
        patient = db.query(Patient).filter(Patient.patient_id == patient_id).first()
        if not patient:
            raise HTTPException(status_code=404, detail="Patient not found")

        admission = (
            db.query(Admission)
            .filter(Admission.patient_id == patient_id)
            .order_by(Admission.admitted_at.desc())
            .first()
        )

        reports = (
            db.query(DiagnosticReport)
            .filter(DiagnosticReport.patient_id == patient_id)
            .order_by(DiagnosticReport.created_at.desc())
            .all()
        )

        reports_list = [
            {
                "report_id": str(r.report_id),
                "department": r.department,
                "test_name": r.test_name,
                "parameters": r.parameters or {},
                "notes": r.technician_notes,
                "technician": r.technician_name,
                "created_at": r.created_at.strftime("%b %d, %Y - %I:%M %p") if r.created_at else None
            }
            for r in reports
        ]

        return {
            "patient_mrn": patient.patient_id,
            "patient_name": f"{patient.first_name} {patient.last_name}".strip(),
            "age": patient.age or 45,
            "gender": patient.gender or "Male",
            "blood_group": patient.blood_group or "O+",
            "phone_number": patient.phone_number or "--",
            "address": patient.address or "--",
            "admission": {
                "admission_id": str(admission.admission_id) if admission else None,
                "bed_id": admission.bed_id if admission else "--",
                "diagnosis": admission.primary_diagnosis if admission else "--",
                "admission_type": admission.admission_type if admission else "Emergency",
                "attending_doctor": admission.attending_doctor if admission else "Dr. Robert Vance",
                "admitted_at": admission.admitted_at.strftime("%b %d, %Y - %I:%M %p") if admission and admission.admitted_at else "--",
                "discharged_at": admission.discharged_at.strftime("%b %d, %Y - %I:%M %p") if admission and admission.discharged_at else "Currently Inpatient",
                "discharge_type": admission.discharge_type if admission and admission.discharge_type else "Active Care"
            },
            "telemetry_summary": {
                "pump_id": "SP01-MULTI",
                "total_volume_ml": 28.5,
                "avg_pressure_kpa": 38.2
            },
            "total_reports": len(reports_list),
            "reports": reports_list
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/v1/discharged-records")
def get_discharged_records(db: Session = Depends(get_db)):
    try:
        admissions = (
            db.query(Admission)
            .filter(Admission.status == "DISCHARGED")
            .order_by(Admission.discharged_at.desc())
            .all()
        )

        records = []
        for adm in admissions:
            patient = db.query(Patient).filter(Patient.patient_id == adm.patient_id).first()
            bed = db.query(Bed).filter(Bed.bed_id == adm.bed_id).first()

            records.append({
                "association_id": str(adm.admission_id),
                "patient_id": patient.patient_id if patient else adm.patient_id,
                "patient_name": f"{patient.first_name} {patient.last_name}".strip() if patient else "Patient",
                "bed_number": bed.bed_number if bed else adm.bed_id,
                "paired_at": adm.admitted_at.isoformat() if adm.admitted_at else None,
                "discharged_at": adm.discharged_at.isoformat() if adm.discharged_at else None,
                "discharge_type": adm.discharge_type or "Routine"
            })

        return records
    except Exception as e:
        return []

# --- WebSockets ---
connected_websockets = set()

@app.websocket("/ws/telemetry")
async def websocket_telemetry_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected_websockets.add(websocket)

    redis_url = os.getenv("REDIS_URL") or os.getenv("REDIS_HOST")

    if redis_url and redis_url != "localhost":
        try:
            if redis_url.startswith("redis://") or redis_url.startswith("rediss://"):
                r = aioredis.from_url(redis_url)
            else:
                r = aioredis.Redis(host=redis_url, port=int(os.getenv("REDIS_PORT", "6379")), db=0)

            pubsub = r.pubsub()
            await pubsub.subscribe("channel:telemetry")

            while True:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message and message.get("type") == "message":
                    data = message["data"].decode("utf-8") if isinstance(message["data"], bytes) else message["data"]
                    await websocket.send_text(data)
                await asyncio.sleep(0.05)
        except Exception:
            pass
        finally:
            connected_websockets.discard(websocket)
    else:
        try:
            while True:
                await asyncio.sleep(1)
        except Exception:
            pass
        finally:
            connected_websockets.discard(websocket)
