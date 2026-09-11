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
from app.models.models import Ward, Bed, Pump, Patient, Admission, DeviceAssociation, PumpTelemetryLog, DiagnosticReport

# Create tables
Base.metadata.create_all(bind=engine)

def run_db_migrations():
    """Ensure all required columns exist in PostgreSQL."""
    try:
        with engine.begin() as conn:
            conn.execute(text("""
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
            """))
            print("[✓] Multi-device schema migrations executed successfully.")
    except Exception as e:
        print(f"[!] Migration notice: {e}")

app = FastAPI(title="Pulse Multi-Device Enterprise HIS & Telemetry Suite")

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

# --- Pydantic Schemas ---
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
    primary_diagnosis: Optional[str] = "Acute Hemodynamic Monitoring"

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
    patient_mrn: Optional[str] = None
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
    return {"status": "online", "system": "Pulse Multi-Device Central Telemetry Station"}

@app.get("/api/v1/registry-status")
def get_registry_status(db: Session = Depends(get_db)):
    """Fetch all active bed encounters and their dynamically attached devices."""
    try:
        # Fetch all occupied/active admissions
        active_admissions = (
            db.query(Admission)
            .filter(Admission.status == "ADMITTED")
            .order_by(Admission.admitted_at.desc())
            .all()
        )

        bed_list = []
        busy_beds = set()

        for adm in active_admissions:
            busy_beds.add(adm.bed_id)
            patient = db.query(Patient).filter(Patient.patient_id == adm.patient_id).first()
            bed = db.query(Bed).filter(Bed.bed_id == adm.bed_id).first()
            bed_num = bed.bed_number if bed else adm.bed_id

            # Query all active devices attached to this admission
            active_devices = (
                db.query(DeviceAssociation)
                .filter(
                    DeviceAssociation.admission_id == adm.admission_id,
                    DeviceAssociation.unpaired_at.is_(None)
                )
                .all()
            )

            dev_list = []
            for d in active_devices:
                # Resolve device type
                dtype = getattr(d, "device_type", None)
                if not dtype:
                    if d.pump_id.startswith("PM-"):
                        dtype = "PATIENT_MONITOR"
                    elif d.pump_id.startswith("DL-"):
                        dtype = "DIALYSIS"
                    else:
                        dtype = "SYRINGE_PUMP"

                dev_list.append({
                    "association_id": str(d.association_id),
                    "device_id": d.pump_id,
                    "device_type": dtype,
                    "paired_at": d.paired_at.isoformat() if d.paired_at else None
                })

            p_name = f"{patient.first_name} {patient.last_name}".strip() if patient else "Patient"

            bed_list.append({
                "bed_id": str(adm.bed_id),
                "bed_number": bed_num,
                "admission_id": str(adm.admission_id),
                "patient_mrn": patient.patient_id if patient else adm.patient_id,
                "patient_name": p_name,
                "age": patient.age if patient else 45,
                "gender": patient.gender if patient else "Male",
                "blood_group": patient.blood_group if patient else "O+",
                "admission_type": adm.admission_type,
                "attending_doctor": adm.attending_doctor,
                "admitted_at": adm.admitted_at.isoformat() if adm.admitted_at else None,
                "devices": dev_list
            })

        # Calculate next suggested bed index
        idx = 1
        while f"ICU-B{idx}" in busy_beds:
            idx += 1
        next_bed = f"ICU-B{idx}"

        total_patients = db.query(Patient).count()
        next_mrn = f"PTN-{str(total_patients + 1).zfill(6)}"

        return {
            "active_associations": bed_list,
            "beds": bed_list,
            "next_suggestions": {
                "bed": next_bed,
                "mrn": next_mrn
            }
        }
    except Exception as e:
        print(f"[!] Registry status error: {e}")
        return {"active_associations": [], "beds": [], "next_suggestions": {"bed": "ICU-B1", "mrn": "PTN-000001"}}

@app.post("/api/v1/admit-patient")
def admit_patient(req: AdmitPatientRequest, db: Session = Depends(get_db)):
    """Admit patient to an ICU Bed directly without requiring an upfront device."""
    try:
        now = datetime.now(timezone.utc)

        # 1. Ensure Ward exists
        ward = db.query(Ward).filter(Ward.ward_id == "icu-ward-a").first()
        if not ward:
            ward = Ward(ward_id="icu-ward-a", name="Main ICU Wing", ward_type="ICU")
            db.add(ward)
            db.flush()

        # 2. Ensure Bed exists & check occupancy
        bed = db.query(Bed).filter((Bed.bed_id == req.bed_number) | (Bed.bed_number == req.bed_number)).first()
        if not bed:
            bed = Bed(
                bed_id=req.bed_number,
                ward_id="icu-ward-a",
                bed_number=req.bed_number,
                current_status="OCCUPIED"
            )
            db.add(bed)
            db.flush()
        else:
            bed.current_status = "OCCUPIED"

        # 3. Create or update Patient record
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
        else:
            patient.first_name = first_name
            patient.last_name = last_name
            patient.age = req.age
            patient.gender = req.gender
            patient.blood_group = req.blood_group
            patient.phone_number = req.phone_number
            patient.address = req.address

        # 4. Create active Admission Encounter
        admission = Admission(
            admission_id=uuid.uuid4(),
            patient_id=patient.patient_id,
            bed_id=bed.bed_id,
            primary_diagnosis=req.primary_diagnosis or "Acute Hemodynamic Monitoring",
            admission_type=req.admission_type or "Emergency",
            attending_doctor=req.attending_doctor or "Dr. Robert Vance",
            admitted_at=now,
            status="ADMITTED"
        )
        db.add(admission)
        db.commit()

        return {"status": "success", "bed_number": req.bed_number, "patient_mrn": req.patient_mrn}
    except Exception as e:
        db.rollback()
        print(f"[!] Admission error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/devices/attach")
def attach_device_to_bed(req: AttachDeviceRequest, db: Session = Depends(get_db)):
    """Dynamically attach any telemetry device (PM, SP, DL) to an active bed."""
    try:
        now = datetime.now(timezone.utc)

        # Ensure device isn't already active elsewhere
        existing_active = db.query(DeviceAssociation).filter(
            DeviceAssociation.pump_id == req.device_id,
            DeviceAssociation.unpaired_at.is_(None)
        ).first()

        if existing_active:
            raise HTTPException(
                status_code=400,
                detail=f"Hardware {req.device_id} is already in active use at another bed!"
            )

        # Locate active admission for this bed
        adm = None
        if req.admission_id:
            try:
                adm_uuid = uuid.UUID(req.admission_id)
                adm = db.query(Admission).filter(Admission.admission_id == adm_uuid).first()
            except ValueError:
                pass

        if not adm:
            bed = db.query(Bed).filter((Bed.bed_id == req.bed_number) | (Bed.bed_number == req.bed_number)).first()
            bed_id = bed.bed_id if bed else req.bed_number
            adm = db.query(Admission).filter(
                Admission.bed_id == bed_id,
                Admission.status == "ADMITTED"
            ).order_by(Admission.admitted_at.desc()).first()

        if not adm:
            raise HTTPException(status_code=404, detail=f"No active admitted patient found at bed {req.bed_number}")

        # Ensure device exists in Pump/Device registry
        pump_rec = db.query(Pump).filter(Pump.pump_id == req.device_id).first()
        if not pump_rec:
            model_map = {
                "PATIENT_MONITOR": "Pulse Multi-Para PM-10",
                "SYRINGE_PUMP": "Pulse SP-01",
                "DIALYSIS": "Pulse CRRT-DL5"
            }
            pump_rec = Pump(
                pump_id=req.device_id,
                model_name=model_map.get(req.device_type, "Pulse Hardware"),
                firmware_version="v2.1.0",
                status="ONLINE"
            )
            db.add(pump_rec)
            db.flush()

        assoc = DeviceAssociation(
            association_id=uuid.uuid4(),
            admission_id=adm.admission_id,
            bed_id=adm.bed_id,
            pump_id=req.device_id,
            paired_at=now,
            paired_by_user_id="DUTY-NURSE-01"
        )
        # Store device_type if column exists
        if hasattr(assoc, "device_type"):
            setattr(assoc, "device_type", req.device_type)

        db.add(assoc)
        db.commit()

        return {"status": "success", "device_id": req.device_id, "bed_number": req.bed_number}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/devices/unbind")
def unbind_single_device(req: UnbindDeviceRequest, db: Session = Depends(get_db)):
    """Release a single device without discharging the patient."""
    try:
        now = datetime.now(timezone.utc)
        assoc = db.query(DeviceAssociation).filter(
            DeviceAssociation.pump_id == req.device_id,
            DeviceAssociation.unpaired_at.is_(None)
        ).first()

        if not assoc:
            raise HTTPException(status_code=404, detail="No active device association found.")

        assoc.unpaired_at = now
        db.commit()
        return {"status": "success", "message": f"Device {req.device_id} released successfully."}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/discharge-encounter")
def discharge_encounter(req: DischargeEncounterRequest, db: Session = Depends(get_db)):
    """Discharge patient encounter and release bed + all attached hardware."""
    try:
        now = datetime.now(timezone.utc)
        bed = db.query(Bed).filter((Bed.bed_id == req.bed_number) | (Bed.bed_number == req.bed_number)).first()
        bed_id = bed.bed_id if bed else req.bed_number

        adm = db.query(Admission).filter(
            Admission.bed_id == bed_id,
            Admission.status == "ADMITTED"
        ).order_by(Admission.admitted_at.desc()).first()

        if adm:
            adm.status = "DISCHARGED"
            adm.discharged_at = now
            adm.discharge_type = req.discharge_type

            # Unbind all currently attached devices
            active_devices = db.query(DeviceAssociation).filter(
                DeviceAssociation.admission_id == adm.admission_id,
                DeviceAssociation.unpaired_at.is_(None)
            ).all()

            for d in active_devices:
                d.unpaired_at = now

        if bed:
            bed.current_status = "AVAILABLE"

        db.commit()
        return {"status": "success", "message": f"Bed {req.bed_number} discharged and all hardware released."}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/reports/attach")
def attach_diagnostic_report(req: ReportAttachRequest, db: Session = Depends(get_db)):
    """Attach blood/lab/scan diagnostics directly to patient encounter."""
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
    """Fetch unified dossier with demographics, admission info, diagnostic reports, and telemetry audit."""
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

        telemetry_stats = {"total_volume_ml": 0.0, "avg_pressure_kpa": 0.0, "pump_id": "--"}
        if admission:
            assoc = (
                db.query(DeviceAssociation)
                .filter(DeviceAssociation.admission_id == admission.admission_id)
                .order_by(DeviceAssociation.paired_at.desc())
                .first()
            )
            if assoc:
                telemetry_stats["pump_id"] = assoc.pump_id
                t_sum = db.execute(
                    text("""
                        SELECT 
                            COALESCE(MAX(volume_infused_ml), 0) as total_vol,
                            COALESCE(AVG(pressure_kpa), 0) as avg_p
                        FROM pump_telemetry_logs
                        WHERE pump_id = :pid
                          AND recorded_at >= :p_start
                    """),
                    {"pid": assoc.pump_id, "p_start": assoc.paired_at}
                ).fetchone()
                if t_sum:
                    telemetry_stats["total_volume_ml"] = float(t_sum[0])
                    telemetry_stats["avg_pressure_kpa"] = round(float(t_sum[1]), 1)

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
                "discharge_type": admission.discharge_type if admission and admission.discharge_type else "In Care / Active"
            },
            "telemetry_summary": telemetry_stats,
            "total_reports": len(reports_list),
            "reports": reports_list
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/v1/discharged-records")
def get_discharged_records(db: Session = Depends(get_db)):
    """Fetch complete historical audit logs for all discharged patient encounters."""
    try:
        admissions = (
            db.query(Admission)
            .filter(Admission.status == "DISCHARGED")
            .order_by(Admission.discharged_at.desc())
            .all()
        )

        audit_data = []
        for adm in admissions:
            patient = db.query(Patient).filter(Patient.patient_id == adm.patient_id).first()
            bed = db.query(Bed).filter(Bed.bed_id == adm.bed_id).first()

            audit_data.append({
                "association_id": str(adm.admission_id),
                "patient_id": patient.patient_id if patient else adm.patient_id,
                "patient_name": f"{patient.first_name} {patient.last_name}".strip() if patient else "Patient",
                "bed_number": bed.bed_number if bed else adm.bed_id,
                "paired_at": adm.admitted_at.isoformat() if adm.admitted_at else None,
                "discharged_at": adm.discharged_at.isoformat() if adm.discharged_at else None,
                "discharge_type": adm.discharge_type or "Routine",
            })

        return audit_data
    except Exception as e:
        print(f"[!] Error loading discharge history: {e}")
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
