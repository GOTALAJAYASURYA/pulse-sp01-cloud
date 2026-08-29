import asyncio
import json
from datetime import datetime, timezone
import uuid
import redis.asyncio as aioredis
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.core.database import SessionLocal
from app.mqtt.worker import start_mqtt_worker
from app.simulator_runner import start_cloud_simulator
from app.models.models import Ward, Bed, Pump, Patient, Admission, DeviceAssociation, PumpTelemetryLog

app = FastAPI(title="Pulse SP-01 Central Telemetry & Smart Ward System")

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
async def startup_event():
    start_mqtt_worker()
    start_cloud_simulator()

# --- Schemas ---
class PairRequest(BaseModel):
    bed_number: str
    patient_mrn: str
    patient_name: str
    pump_id: str

class DischargeRequest(BaseModel):
    pump_id: str

# --- REST Endpoints ---
'''
@app.get("/api/v1/registry-status")
def get_registry_status(db: Session = Depends(get_db)):
    """Fetch active fleet associations and calculate the next auto-increment IDs."""
    try:
        # Query active associations with all related models via ORM
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
            bed_no = bed.bed_number if bed else "ICU-B1"
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
                "paired_at": da.paired_at.isoformat() if da.paired_at else None
            })

        total_patients = db.query(Patient).count()
        total_pumps = db.query(Pump).count()

        next_seq = max(len(active_assocs) + 1, total_pumps + 1)
        next_pat_seq = max(len(active_assocs) + 1, total_patients + 1)

        next_bed = f"ICU-B{len(active_assocs) + 1}"
        next_mrn = f"PTN-{str(next_pat_seq).zfill(6)}"
        next_pump = f"SP01-2026-{str(next_seq).zfill(4)}"

        return {
            "active_associations": res_list,
            "busy_pumps": list(busy_pumps),
            "busy_beds": list(busy_beds),
            "next_suggestions": {
                "bed": next_bed,
                "mrn": next_mrn,
                "pump": next_pump
            }
        }
    except Exception as e:
        print(f"[!] Registry status error: {e}")
        return {
            "active_associations": [],
            "busy_pumps": [],
            "busy_beds": [],
            "next_suggestions": {"bed": "ICU-B1", "mrn": "PTN-000001", "pump": "SP01-2026-0001"}
        }
'''

@app.get("/api/v1/registry-status")
def get_registry_status(db: Session = Depends(get_db)):
    """Fetch active fleet associations and recycle free Beds/Pumps before incrementing."""
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

            p_name = f"{patient.first_name} {patient.last_name}".strip() if patient else "ABC"
            p_mrn = patient.patient_id if patient else "PTN-000001"

            res_list.append({
                "association_id": str(da.association_id),
                "pump_id": da.pump_id,
                "bed_number": bed_no,
                "patient_mrn": p_mrn,
                "patient_name": p_name,
                "paired_at": da.paired_at.isoformat() if da.paired_at else None
            })

        # 1. Reuse existing free beds or allocate the lowest available index
        all_existing_beds = [b.bed_number for b in db.query(Bed).all()]
        free_beds = sorted([b for b in all_existing_beds if b not in busy_beds])
        
        if free_beds:
            next_bed = free_beds[0]
        else:
            # Find the lowest missing ICU-B# index
            idx = 1
            while f"ICU-B{idx}" in busy_beds:
                idx += 1
            next_bed = f"ICU-B{idx}"

        # 2. Reuse existing free pumps or allocate the lowest available index
        all_existing_pumps = [p.pump_id for p in db.query(Pump).all()]
        free_pumps = sorted([p for p in all_existing_pumps if p not in busy_pumps])
        
        if free_pumps:
            next_pump = free_pumps[0]
        else:
            # Find the lowest missing SP01-2026-#### index
            p_idx = 1
            while f"SP01-2026-{str(p_idx).zfill(4)}" in busy_pumps:
                p_idx += 1
            next_pump = f"SP01-2026-{str(p_idx).zfill(4)}"

        # 3. Always increment Patient MRN monotonically
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
                "name": "ABC"
            }
        }
    except Exception as e:
        print(f"[!] Registry status error: {e}")
        return {
            "active_associations": [],
            "busy_pumps": [],
            "busy_beds": [],
            "next_suggestions": {"bed": "ICU-B1", "mrn": "PTN-000001", "pump": "SP01-2026-0001", "name": "ABC"}
        }

@app.post("/api/v1/pair")
def pair_device(req: PairRequest, db: Session = Depends(get_db)):
    """Bind Bed + Patient + Admission + Syringe Pump using the exact schema models."""
    try:
        now = datetime.now(timezone.utc)

        # 1. Guardrail: Pump must not be active elsewhere
        existing_assoc = db.query(DeviceAssociation).filter(
            DeviceAssociation.pump_id == req.pump_id,
            DeviceAssociation.unpaired_at.is_(None)
        ).first()

        if existing_assoc:
            raise HTTPException(
                status_code=400,
                detail=f"Pump {req.pump_id} is currently in an active infusion! Discharge it first."
            )

        # 2. Ensure Ward exists
        ward = db.query(Ward).filter(Ward.ward_id == "icu-ward-a").first()
        if not ward:
            ward = Ward(ward_id="icu-ward-a", name="Main ICU Wing", ward_type="ICU")
            db.add(ward)
            db.flush()

        # 3. Get or create Bed
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

        # 4. Get or create Pump
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

        # 5. Get or create Patient
        patient = db.query(Patient).filter(Patient.patient_id == req.patient_mrn).first()
        if not patient:
            name_parts = req.patient_name.strip().split(" ", 1)
            first_name = name_parts[0] if name_parts[0] else "Patient"
            last_name = name_parts[1] if len(name_parts) > 1 else "Doe"

            patient = Patient(
                patient_id=req.patient_mrn,
                first_name=first_name,
                last_name=last_name
            )
            db.add(patient)
            db.flush()

        # 6. Create active Admission
        admission = Admission(
            admission_id=uuid.uuid4(),
            patient_id=patient.patient_id,
            bed_id=bed.bed_id,
            primary_diagnosis="Active ICU Clinical Infusion",
            admitted_at=now,
            status="ADMITTED"
        )
        db.add(admission)
        db.flush()

        # 7. Create DeviceAssociation
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
        print(f"[!] Pairing error: {e}")
        return {"status": "error", "message": str(e)}

@app.post("/api/v1/discharge")
def discharge_patient(req: DischargeRequest, db: Session = Depends(get_db)):
    """Discharge patient and release pump for reuse while preserving all historical telemetry logs."""
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
            
            bed = db.query(Bed).filter(Bed.bed_id == assoc.bed_id).first()
            if bed:
                bed.current_status = "AVAILABLE"

            db.commit()
            return {"status": "success", "message": f"Pump {req.pump_id} released."}
        
        return {"status": "error", "message": "No active association found."}
    except Exception as e:
        db.rollback()
        return {"status": "error", "message": str(e)}

@app.get("/api/v1/history/{pump_id}")
def get_pump_history(pump_id: str, db: Session = Depends(get_db)):
    """Fetch time-series telemetry logs from TimescaleDB."""
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
    """Fetch complete historical audit logs for all discharged patient sessions."""
    try:
        # Fetch all past sessions where unpaired_at is NOT null
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

            # Calculate total volume delivered and total alarms during this specific session
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
                "patient_name": f"{patient.first_name} {patient.last_name}".strip() if patient else "Unknown Patient",
                "bed_number": bed.bed_number if bed else r.bed_id,
                "pump_id": r.pump_id,
                "paired_at": r.paired_at.isoformat() if r.paired_at else None,
                "discharged_at": r.unpaired_at.isoformat() if r.unpaired_at else None,
                "total_volume_ml": float(telemetry_summary[0]) if telemetry_summary else 0.0,
                "avg_pressure_kpa": round(float(telemetry_summary[1]), 1) if telemetry_summary else 0.0,
                "session_points": int(telemetry_summary[2]) if telemetry_summary else 0
            })

        return audit_data
    except Exception as e:
        print(f"[!] Error loading discharge history: {e}")
        return []


# --- WebSockets ---
@app.websocket("/ws/telemetry")
async def websocket_telemetry_endpoint(websocket: WebSocket):
    await websocket.accept()
    redis_url = os.getenv("REDIS_HOST", "localhost")
    if redis_url.startswith("redis://"):
        r = aioredis.from_url(redis_url)
    else:
        r = aioredis.Redis(host=redis_url, port=int(os.getenv("REDIS_PORT", "6379")), db=0)
        
    pubsub = r.pubsub()
    await pubsub.subscribe("channel:telemetry")
    
    try:
        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message and message.get("type") == "message":
                data = message["data"].decode("utf-8")
                await websocket.send_text(data)
            await asyncio.sleep(0.05)
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        await pubsub.unsubscribe("channel:telemetry")
        await pubsub.close()
        await r.close()

'''
@app.websocket("/ws/telemetry")
async def websocket_telemetry_endpoint(websocket: WebSocket):
    await websocket.accept()
    r = aioredis.Redis(host="localhost", port=6379, db=0)
    pubsub = r.pubsub()
    await pubsub.subscribe("channel:telemetry")
    
    try:
        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message and message.get("type") == "message":
                data = message["data"].decode("utf-8")
                await websocket.send_text(data)
            await asyncio.sleep(0.05)
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        await pubsub.unsubscribe("channel:telemetry")
        await pubsub.close()
        await r.close() '''
        
