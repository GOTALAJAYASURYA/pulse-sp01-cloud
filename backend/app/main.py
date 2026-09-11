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
from app.simulator_runner import start_multi_device_simulator
from app.models.models import Ward, Bed, Device, Patient, Admission, DeviceAssociation, MultiDeviceTelemetryLog, DiagnosticReport

Base.metadata.create_all(bind=engine)

def run_db_migrations():
    """Defensive schema migration for multi-device support."""
    try:
        with engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS devices (
                    device_id VARCHAR(64) PRIMARY KEY,
                    device_type VARCHAR(30) NOT NULL,
                    model_name VARCHAR(50) DEFAULT 'Pulse Pro Series',
                    firmware_version VARCHAR(30) DEFAULT 'v2.1.0',
                    status VARCHAR(30) DEFAULT 'ONLINE',
                    last_heartbeat TIMESTAMP WITH TIME ZONE
                );

                CREATE TABLE IF NOT EXISTS multi_device_telemetry_logs (
                    recorded_at TIMESTAMP WITH TIME ZONE NOT NULL,
                    device_id VARCHAR(64) NOT NULL,
                    device_type VARCHAR(30) NOT NULL,
                    telemetry_data JSON NOT NULL,
                    PRIMARY KEY (recorded_at, device_id)
                );

                ALTER TABLE device_associations ADD COLUMN IF NOT EXISTS device_id VARCHAR(64);
                ALTER TABLE device_associations ADD COLUMN IF NOT EXISTS device_type VARCHAR(30) DEFAULT 'SYRINGE_PUMP';
            """))
            print("[✓] Multi-device schema migrations applied.")
    except Exception as e:
        print(f"[!] Migration warning: {e}")

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
    start_multi_device_simulator()

# --- Schemas ---
class AdmitPatientRequest(BaseModel):
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
    primary_diagnosis: Optional[str] = "Acute Clinical ICU Care"

class AttachDeviceRequest(BaseModel):
    bed_number: str
    device_id: str
    device_type: str  # "SYRINGE_PUMP", "PATIENT_MONITOR", "DIALYSIS"

class DetachDeviceRequest(BaseModel):
    device_id: str

class DischargeRequest(BaseModel):
    bed_number: str
    discharge_type: Optional[str] = "Routine / Recovered"

class ReportAttachRequest(BaseModel):
    patient_mrn: str
    department: str
    test_name: str
    parameters: dict
    technician_notes: str = ""
    technician_name: str = "Diagnostic Staff"


# --- Endpoints ---

@app.get("/")
def health_check():
    return {"status": "online", "system": "Pulse Multi-Device Telemetry Engine"}

@app.get("/api/v1/registry-status")
def get_registry_status(db: Session = Depends(get_db)):
    """Fetch active ward beds, their dynamically attached hardware racks, and free suggestions."""
    try:
        # 1. Fetch active admissions
        active_admissions = (
            db.query(Admission)
            .filter(Admission.status == "ADMITTED")
            .order_by(Admission.admitted_at.desc())
            .all()
        )

        active_beds = []
        busy_beds = set()
        busy_devices = set()

        for adm in active_admissions:
            patient = db.query(Patient).filter(Patient.patient_id == adm.patient_id).first()
            bed = db.query(Bed).filter(Bed.bed_id == adm.bed_id).first()
            bed_no = bed.bed_number if bed else adm.bed_id
            busy_beds.add(bed_no)

            # Get all active devices attached to this admission
            active_dev_assocs = (
                db.query(DeviceAssociation)
                .filter(
                    DeviceAssociation.admission_id == adm.admission_id,
                    DeviceAssociation.unpaired_at.is_(None)
                )
                .all()
            )

            attached_devices = []
            for da in active_dev_assocs:
                busy_devices.add(da.device_id)
                attached_devices.append({
                    "association_id": str(da.association_id),
                    "device_id": da.device_id,
                    "device_type": da.device_type,
                    "paired_at": da.paired_at.isoformat() if da.paired_at else None
                })

            p_name = f"{patient.first_name} {patient.last_name}".strip() if patient else "Patient"

            active_beds.append({
                "admission_id": str(adm.admission_id),
                "bed_number": bed_no,
                "patient_mrn": patient.patient_id if patient else "PTN-000001",
                "patient_name": p_name,
                "age": patient.age if patient else 45,
                "gender": patient.gender if patient else "Male",
                "blood_group": patient.blood_group if patient else "O+",
                "admission_type": adm.admission_type,
                "attending_doctor": adm.attending_doctor,
                "admitted_at": adm.admitted_at.isoformat() if adm.admitted_at else None,
                "attached_devices": attached_devices
            })

        # Suggestions
        idx = 1
        while f"ICU-B{idx}" in busy_beds:
            idx += 1
        next_bed = f"ICU-B{idx}"

        total_patients = db.query(Patient).count()
        next_mrn = f"PTN-{str(total_patients + 1).zfill(6)}"

        # Next suggestions for each device type
        sp_idx = 1
        while f"SP01-2026-{str(sp_idx).zfill(4)}" in busy_devices:
            sp_idx += 1
        next_sp = f"SP01-2026-{str(sp_idx).zfill(4)}"

        pm_idx = 1
        while f"PM-2026-{str(pm_idx).zfill(4)}" in busy_devices:
            pm_idx += 1
        next_pm = f"PM-2026-{str(pm_idx).zfill(4)}"

        dl_idx = 1
        while f"DL-2026-{str(dl_idx).zfill(4)}" in busy_devices:
            dl_idx += 1
        next_dl = f"DL-2026-{str(dl_idx).zfill(4)}"

        return {
            "active_beds": active_beds,
            "busy_devices": list(busy_devices),
            "next_suggestions": {
                "bed": next_bed,
                "mrn": next_mrn,
                "device_sp": next_sp,
                "device_pm": next_pm,
                "device_dl": next_dl
            }
        }
    except Exception as e:
        print(f"[!] Registry status error: {e}")
        return {"active_beds": [], "busy_devices": [], "next_suggestions": {}}

@app.post("/api/v1/admit-patient")
def admit_patient(req: AdmitPatientRequest, db: Session = Depends(get_db)):
    """Admit a patient directly to a bed station with ZERO attached devices initially."""
    try:
        now = datetime.now(timezone.utc)

        # 1. Ward & Bed Setup
        ward = db.query(Ward).filter(Ward.ward_id == "icu-ward-a").first()
        if not ward:
            ward = Ward(ward_id="icu-ward-a", name="Main ICU Wing", ward_type="ICU")
            db.add(ward)
            db.flush()

        bed = db.query(Bed).filter((Bed.bed_id == req.bed_number) | (Bed.bed_number == req.bed_number)).first()
        if not bed:
            bed = Bed(bed_id=req.bed_number, ward_id="icu-ward-a", bed_number=req.bed_number, current_status="OCCUPIED")
            db.add(bed)
            db.flush()
        else:
            bed.current_status = "OCCUPIED"

        # 2. Patient Demographics
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

        # 3. Create active encounter
        admission = Admission(
            admission_id=uuid.uuid4(),
            patient_id=patient.patient_id,
            bed_id=bed.bed_id,
            primary_diagnosis=req.primary_diagnosis or "ICU Critical Care",
            admission_type=req.admission_type or "Emergency",
            attending_doctor=req.attending_doctor or "Dr. Robert Vance",
            admitted_at=now,
            status="ADMITTED"
        )
        db.add(admission)
        db.commit()

        return {"status": "success", "message": f"Patient admitted to {req.bed_number}", "bed_number": req.bed_number}
    except Exception as e:
        db.rollback()
        return {"status": "error", "message": str(e)}

@app.post("/api/v1/devices/attach")
def attach_device_to_bed(req: AttachDeviceRequest, db: Session = Depends(get_db)):
    """Dynamically attach PM, SP, or Dialysis device to an active patient bed."""
    try:
        now = datetime.now(timezone.utc)

        # 1. Device check
        existing_active = db.query(DeviceAssociation).filter(
            DeviceAssociation.device_id == req.device_id,
            DeviceAssociation.unpaired_at.is_(None)
        ).first()

        if existing_active:
            raise HTTPException(status_code=400, detail=f"Device {req.device_id} is already in use elsewhere!")

        # 2. Find active admission for bed
        bed = db.query(Bed).filter((Bed.bed_id == req.bed_number) | (Bed.bed_number == req.bed_number)).first()
        if not bed:
            raise HTTPException(status_code=404, detail=f"Bed {req.bed_number} not found.")

        active_adm = db.query(Admission).filter(
            Admission.bed_id == bed.bed_id,
            Admission.status == "ADMITTED"
        ).first()

        if not active_adm:
            raise HTTPException(status_code=400, detail=f"No active patient in bed {req.bed_number}.")

        # 3. Register device if new
        dev = db.query(Device).filter(Device.device_id == req.device_id).first()
        if not dev:
            dev = Device(
                device_id=req.device_id,
                device_type=req.device_type.upper(),
                model_name=f"Pulse {req.device_type.replace('_', ' ').title()}",
                status="ONLINE"
            )
            db.add(dev)
            db.flush()

        # 4. Bind association
        assoc = DeviceAssociation(
            association_id=uuid.uuid4(),
            admission_id=active_adm.admission_id,
            bed_id=bed.bed_id,
            device_id=dev.device_id,
            device_type=dev.device_type,
            paired_at=now
        )
        db.add(assoc)
        db.commit()

        return {"status": "success", "message": f"{req.device_type} {req.device_id} attached to {req.bed_number}"}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        return {"status": "error", "message": str(e)}

@app.post("/api/v1/devices/detach")
def detach_device(req: DetachDeviceRequest, db: Session = Depends(get_db)):
    """Release single hardware device back to inventory without discharging patient."""
    try:
        now = datetime.now(timezone.utc)
        assoc = db.query(DeviceAssociation).filter(
            DeviceAssociation.device_id == req.device_id,
            DeviceAssociation.unpaired_at.is_(None)
        ).first()

        if not assoc:
            return {"status": "error", "message": "Device is not currently attached."}

        assoc.unpaired_at = now
        db.commit()
        return {"status": "success", "message": f"Device {req.device_id} released successfully."}
    except Exception as e:
        db.rollback()
        return {"status": "error", "message": str(e)}

@app.post("/api/v1/discharge")
def discharge_patient(req: DischargeRequest, db: Session = Depends(get_db)):
    """Discharge patient and unpair all attached devices at once."""
    try:
        now = datetime.now(timezone.utc)
        bed = db.query(Bed).filter((Bed.bed_id == req.bed_number) | (Bed.bed_number == req.bed_number)).first()
        if not bed:
            return {"status": "error", "message": "Bed not found"}

        adm = db.query(Admission).filter(
            Admission.bed_id == bed.bed_id,
            Admission.status == "ADMITTED"
        ).first()

        if adm:
            adm.status = "DISCHARGED"
            adm.discharged_at = now
            adm.discharge_type = req.discharge_type

            # Unpair all attached devices
            assocs = db.query(DeviceAssociation).filter(
                DeviceAssociation.admission_id == adm.admission_id,
                DeviceAssociation.unpaired_at.is_(None)
            ).all()

            for a in assocs:
                a.unpaired_at = now

            bed.current_status = "AVAILABLE"
            db.commit()
            return {"status": "success", "message": f"Patient in {req.bed_number} discharged and all equipment released."}

        return {"status": "error", "message": "No active patient found in this bed."}
    except Exception as e:
        db.rollback()
        return {"status": "error", "message": str(e)}

@app.post("/api/v1/reports/attach")
def attach_diagnostic_report(req: ReportAttachRequest, db: Session = Depends(get_db)):
    try:
        patient = db.query(Patient).filter(Patient.patient_id == req.patient_mrn).first()
        if not patient:
            raise HTTPException(status_code=404, detail=f"Patient with MRN '{req.patient_mrn}' not found.")

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
    try:
        patient = db.query(Patient).filter(Patient.patient_id == patient_id).first()
        if not patient:
            raise HTTPException(status_code=404, detail="Patient not found")

        admission = db.query(Admission).filter(Admission.patient_id == patient_id).order_by(Admission.admitted_at.desc()).first()

        # Gather all equipment attached during encounter
        equipment_used = []
        if admission:
            assocs = db.query(DeviceAssociation).filter(DeviceAssociation.admission_id == admission.admission_id).all()
            equipment_used = [
                {
                    "device_id": a.device_id,
                    "device_type": a.device_type,
                    "paired_at": a.paired_at.strftime("%b %d, %I:%M %p") if a.paired_at else "--",
                    "status": "Currently Active" if not a.unpaired_at else "Released"
                }
                for a in assocs
            ]

        reports = db.query(DiagnosticReport).filter(DiagnosticReport.patient_id == patient_id).order_by(DiagnosticReport.created_at.desc()).all()

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
                "bed_id": admission.bed_id if admission else "--",
                "diagnosis": admission.primary_diagnosis if admission else "--",
                "admission_type": admission.admission_type if admission else "Emergency",
                "attending_doctor": admission.attending_doctor if admission else "Duty Consultant",
                "admitted_at": admission.admitted_at.strftime("%b %d, %Y - %I:%M %p") if admission and admission.admitted_at else "--",
                "discharged_at": admission.discharged_at.strftime("%b %d, %Y - %I:%M %p") if admission and admission.discharged_at else "Currently Inpatient",
                "discharge_type": admission.discharge_type if admission and admission.discharge_type else "Active Stay"
            },
            "equipment_used": equipment_used,
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
            p = db.query(Patient).filter(Patient.patient_id == adm.patient_id).first()
            dev_count = db.query(DeviceAssociation).filter(DeviceAssociation.admission_id == adm.admission_id).count()

            records.append({
                "admission_id": str(adm.admission_id),
                "patient_id": p.patient_id if p else "UNKNOWN",
                "patient_name": f"{p.first_name} {p.last_name}".strip() if p else "Patient",
                "bed_number": adm.bed_id,
                "admission_type": adm.admission_type,
                "discharge_type": adm.discharge_type or "Routine",
                "admitted_at": adm.admitted_at.isoformat() if adm.admitted_at else None,
                "discharged_at": adm.discharged_at.isoformat() if adm.discharged_at else None,
                "devices_utilized": dev_count
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
            r = aioredis.from_url(redis_url) if redis_url.startswith("redis") else aioredis.Redis(host=redis_url, port=6379, db=0)
            pubsub = r.pubsub()
            await pubsub.subscribe("channel:telemetry")
            while True:
                msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if msg and msg.get("type") == "message":
                    data = msg["data"].decode("utf-8") if isinstance(msg["data"], bytes) else msg["data"]
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
