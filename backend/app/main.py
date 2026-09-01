import os
import json
import asyncio
from datetime import datetime, timezone
import uuid
import redis.asyncio as aioredis
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.core.database import SessionLocal, engine, Base
from app.mqtt.worker import start_mqtt_worker
from app.simulator_runner import start_cloud_simulator
from app.models.models import Ward, Bed, Pump, Patient, Admission, DeviceAssociation, PumpTelemetryLog, DiagnosticReport

# Create all database tables immediately on startup
Base.metadata.create_all(bind=engine)

def run_db_migrations():
    """Auto-migrate existing tables with newly added clinical columns."""
    with engine.connect() as conn:
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
        """))
        conn.commit()

app = FastAPI(title="Pulse Enterprise HIS & Telemetry Suite")

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
    try:
        run_db_migrations()
    except Exception as e:
        print(f"[!] Migration warning: {e}")
    start_mqtt_worker()
    start_cloud_simulator()

# --- Schemas ---
class PairRequest(BaseModel):
    bed_number: str
    patient_mrn: str
    patient_name: str
    pump_id: str
    age: Optional[int] = 35
    gender: Optional[str] = "Male"
    blood_group: Optional[str] = "O+"
    phone_number: Optional[str] = ""
    address: Optional[str] = ""
    admission_type: Optional[str] = "Emergency"
    attending_doctor: Optional[str] = "Dr. Robert Vance"
    primary_diagnosis: Optional[str] = "Acute Clinical Stabilization"

class DischargeRequest(BaseModel):
    pump_id: str
    discharge_type: Optional[str] = "Routine / Recovered"

class ReportAttachRequest(BaseModel):
    patient_mrn: str
    department: str
    test_name: str
    parameters: dict
    technician_notes: str = ""
    technician_name: str = "Diagnostic Staff"


# --- REST Endpoints ---

@app.get("/api/v1/registry-status")
def get_registry_status(db: Session = Depends(get_db)):
    """Fetch active fleet associations and compute next available IDs."""
    try:
        active_assocs = (
            db.query(DeviceAssociation)
            .filter(DeviceAssociation.unpaired_at.is_(None))
            .order_by(DeviceAssociation.paired_at.desc())
            .all()
        )

        res_list = []
        busy_pumps = set()
        busy_beds = set()

        for da in active_assocs:
            busy_pumps.add(da.pump_id)
            bed = db.query(Bed).filter(Bed.bed_id == da.bed_id).first()
            bed_no = bed.bed_number if bed else da.bed_id
            busy_beds.add(bed_no)

            admission = db.query(Admission).filter(Admission.admission_id == da.admission_id).first() if da.admission_id else None
            patient = db.query(Patient).filter(Patient.patient_id == admission.patient_id).first() if admission else None

            p_name = f"{patient.first_name} {patient.last_name}".strip() if patient else "Patient"
            p_mrn = patient.patient_id if patient else "PTN-000001"

            res_list.append({
                "association_id": str(da.association_id),
                "pump_id": da.pump_id,
                "bed_number": bed_no,
                "patient_mrn": p_mrn,
                "patient_name": p_name,
                "paired_at": da.paired_at.isoformat() if da.paired_at else None,
                "age": patient.age if patient else 35,
                "gender": patient.gender if patient else "Male",
                "blood_group": patient.blood_group if patient else "O+",
                "admission_type": admission.admission_type if admission else "Emergency",
                "attending_doctor": admission.attending_doctor if admission else "Duty Consultant"
            })

        all_existing_beds = [b.bed_number for b in db.query(Bed).all()]
        free_beds = sorted([b for b in all_existing_beds if b not in busy_beds])
        if free_beds:
            next_bed = free_beds[0]
        else:
            idx = 1
            while f"ICU-B{idx}" in busy_beds:
                idx += 1
            next_bed = f"ICU-B{idx}"

        all_existing_pumps = [p.pump_id for p in db.query(Pump).all()]
        free_pumps = sorted([p for p in all_existing_pumps if p not in busy_pumps])
        if free_pumps:
            next_pump = free_pumps[0]
        else:
            p_idx = 1
            while f"SP01-2026-{str(p_idx).zfill(4)}" in busy_pumps:
                p_idx += 1
            next_pump = f"SP01-2026-{str(p_idx).zfill(4)}"

        total_patients = db.query(Patient).count()
        next_mrn = f"PTN-{str(total_patients + 1).zfill(6)}"

        return {
            "active_associations": res_list,
            "busy_pumps": list(busy_pumps),
            "busy_beds": list(busy_beds),
            "next_suggestions": {
                "bed": next_bed,
                "mrn": next_mrn,
                "pump": next_pump,
                "name": "Patient"
            }
        }
    except Exception as e:
        print(f"[!] Registry status error: {e}")
        return {
            "active_associations": [],
            "busy_pumps": [],
            "busy_beds": [],
            "next_suggestions": {"bed": "ICU-B1", "mrn": "PTN-000001", "pump": "SP01-2026-0001", "name": "Patient"}
        }

@app.post("/api/v1/pair")
def pair_device(req: PairRequest, db: Session = Depends(get_db)):
    """Admit patient with full demographics and bind Bed + Pump."""
    try:
        now = datetime.now(timezone.utc)

        existing_assoc = db.query(DeviceAssociation).filter(
            DeviceAssociation.pump_id == req.pump_id,
            DeviceAssociation.unpaired_at.is_(None)
        ).first()

        if existing_assoc:
            raise HTTPException(
                status_code=400,
                detail=f"Pump {req.pump_id} is currently in an active infusion! Discharge it first."
            )

        # 1. Ensure Ward exists
        ward = db.query(Ward).filter(Ward.ward_id == "icu-ward-a").first()
        if not ward:
            ward = Ward(ward_id="icu-ward-a", name="Main ICU Wing", ward_type="ICU")
            db.add(ward)
            db.flush()

        # 2. Get or create Bed
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

        # 3. Get or create Pump
        pump = db.query(Pump).filter(Pump.pump_id == req.pump_id).first()
        if not pump:
            pump = Pump(
                pump_id=req.pump_id,
                model_name="Pulse SP-01",
                firmware_version="v1.0.4",
                status="ONLINE"
            )
            db.add(pump)
            db.flush()

        # 4. Get or create Patient (No default "Doe" suffix)
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

        # 5. Create active Admission Encounter
        admission = Admission(
            admission_id=uuid.uuid4(),
            patient_id=patient.patient_id,
            bed_id=bed.bed_id,
            primary_diagnosis=req.primary_diagnosis or "Active ICU Clinical Infusion",
            admission_type=req.admission_type or "Emergency",
            attending_doctor=req.attending_doctor or "Dr. Robert Vance",
            admitted_at=now,
            status="ADMITTED"
        )
        db.add(admission)
        db.flush()

        # 6. Create Device Association
        assoc = DeviceAssociation(
            association_id=uuid.uuid4(),
            admission_id=admission.admission_id,
            bed_id=bed.bed_id,
            pump_id=pump.pump_id,
            paired_at=now,
            paired_by_user_id="CLINICAL-NURSE-01"
        )
        db.add(assoc)
        db.commit()

        return {"status": "success", "pump_id": req.pump_id, "bed_number": req.bed_number}

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        return {"status": "error", "message": str(e)}

@app.post("/api/v1/discharge")
def discharge_patient(req: DischargeRequest, db: Session = Depends(get_db)):
    """Discharge patient, record discharge type, and release hardware."""
    try:
        now = datetime.now(timezone.utc)
        assoc = db.query(DeviceAssociation).filter(
            DeviceAssociation.pump_id == req.pump_id,
            DeviceAssociation.unpaired_at.is_(None)
        ).first()

        if assoc:
            assoc.unpaired_at = now
            if assoc.admission_id:
                adm = db.query(Admission).filter(Admission.admission_id == assoc.admission_id).first()
                if adm:
                    adm.status = "DISCHARGED"
                    adm.discharged_at = now
                    adm.discharge_type = req.discharge_type
            
            bed = db.query(Bed).filter(Bed.bed_id == assoc.bed_id).first()
            if bed:
                bed.current_status = "AVAILABLE"

            db.commit()
            return {"status": "success", "message": f"Pump {req.pump_id} released."}
        
        return {"status": "error", "message": "No active association found."}
    except Exception as e:
        db.rollback()
        return {"status": "error", "message": str(e)}

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
    """Fetch unified clinical dossier with full demographics, admission encounter, diagnostic reports, and telemetry audit."""
    try:
        patient = db.query(Patient).filter(Patient.patient_id == patient_id).first()
        if not patient:
            raise HTTPException(status_code=404, detail="Patient not found")

        # Get latest admission encounter
        admission = (
            db.query(Admission)
            .filter(Admission.patient_id == patient_id)
            .order_by(Admission.admitted_at.desc())
            .first()
        )

        # Get device telemetry stats for this encounter
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
            "age": patient.age or 35,
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

@app.get("/api/v1/history/{pump_id}")
def get_pump_history(pump_id: str, db: Session = Depends(get_db)):
    try:
        logs = (
            db.query(PumpTelemetryLog)
            .filter(PumpTelemetryLog.pump_id == pump_id)
            .order_by(PumpTelemetryLog.recorded_at.desc())
            .limit(50)
            .all()
        )
        return [
            {
                "time": r.recorded_at.strftime("%H:%M:%S") if r.recorded_at else "--",
                "rate": float(r.current_rate_ml_hr or 0),
                "pressure": float(r.pressure_kpa or 0),
                "delivered": float(r.volume_infused_ml or 0),
            }
            for r in reversed(logs)
        ]
    except Exception:
        return []

@app.get("/api/v1/discharged-records")
def get_discharged_records(db: Session = Depends(get_db)):
    try:
        records = (
            db.query(DeviceAssociation)
            .filter(DeviceAssociation.unpaired_at.isnot(None))
            .order_by(DeviceAssociation.unpaired_at.desc())
            .all()
        )

        audit_data = []
        for r in records:
            admission = db.query(Admission).filter(Admission.admission_id == r.admission_id).first() if r.admission_id else None
            patient = db.query(Patient).filter(Patient.patient_id == admission.patient_id).first() if admission else None
            bed = db.query(Bed).filter(Bed.bed_id == r.bed_id).first()

            telemetry_summary = db.execute(
                text("""
                    SELECT 
                        COALESCE(MAX(volume_infused_ml), 0) as total_delivered,
                        COALESCE(AVG(pressure_kpa), 0) as avg_pressure,
                        COUNT(*) as data_points
                    FROM pump_telemetry_logs
                    WHERE pump_id = :pid 
                      AND recorded_at >= :p_start 
                      AND recorded_at <= :p_end
                """),
                {"pid": r.pump_id, "p_start": r.paired_at, "p_end": r.unpaired_at}
            ).fetchone()

            audit_data.append({
                "association_id": str(r.association_id),
                "patient_id": patient.patient_id if patient else "PTN-UNKNOWN",
                "patient_name": f"{patient.first_name} {patient.last_name}".strip() if patient else "Patient",
                "bed_number": bed.bed_number if bed else r.bed_id,
                "pump_id": r.pump_id,
                "paired_at": r.paired_at.isoformat() if r.paired_at else None,
                "discharged_at": r.unpaired_at.isoformat() if r.unpaired_at else None,
                "discharge_type": admission.discharge_type if admission and admission.discharge_type else "Routine",
                "total_volume_ml": float(telemetry_summary[0]) if telemetry_summary else 0.0,
                "avg_pressure_kpa": round(float(telemetry_summary[1]), 1) if telemetry_summary else 0.0,
                "session_points": int(telemetry_summary[2]) if telemetry_summary else 0
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
