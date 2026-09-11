import os
import re
import json
import asyncio
import random
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
from app.models.models import Ward, Bed, Pump, Patient, Admission, DeviceAssociation, PumpTelemetryLog, DiagnosticReport

Base.metadata.create_all(bind=engine)

# Standard Hospital Hardware Fleet Pools
FLEET_SP = [f"SP01-2026-{str(i).zfill(4)}" for i in range(1, 21)]       # SP01-2026-0001 to SP01-2026-0020
FLEET_PM = [f"PM01-2026-{i}" for i in range(1001, 1016)]                 # PM01-2026-1001 to PM01-2026-1015
FLEET_DL = [f"DL01-2026-{i}" for i in range(5001, 5006)]                 # DL01-2026-5001 to DL01-2026-5005

def run_db_migrations():
    """Safely apply column additions without crashing the service."""
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
            print("[✓] Schema migrations validated.")
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

# In-memory telemetry cache & active sockets
LIVE_DEVICE_STATE = {}
connected_websockets = set()

async def telemetry_simulation_loop():
    """Generates realistic hospital hemodynamic variations and clinical threshold alarms."""
    while True:
        try:
            db = SessionLocal()
            active_associations = (
                db.query(DeviceAssociation)
                .filter(DeviceAssociation.unpaired_at.is_(None))
                .all()
            )

            for assoc in active_associations:
                dev_id = assoc.pump_id
                dtype = getattr(assoc, "device_type", None) or (
                    "PATIENT_MONITOR" if "PM" in dev_id else ("DIALYSIS" if "DL" in dev_id else "SYRINGE_PUMP")
                )
                alarms = []

                if dtype == "PATIENT_MONITOR":
                    prev = LIVE_DEVICE_STATE.get(dev_id, {}).get("vitals", {})
                    hr = max(45, min(145, prev.get("heart_rate_bpm", 75) + random.choice([-2, -1, 0, 1, 2])))
                    spo2 = max(86, min(100, prev.get("spo2_pct", 98) + random.choice([-1, 0, 0, 1])))
                    sys = max(90, min(160, prev.get("nibp_systolic", 120) + random.choice([-2, 0, 2])))
                    dia = max(55, min(95, prev.get("nibp_diastolic", 80) + random.choice([-1, 0, 1])))
                    raw_temp = max(36.0, min(39.5, prev.get("temp_c", 36.8) + random.choice([-0.1, 0.0, 0.1])))
                    temp = round(raw_temp, 1)
                    resp = max(10, min(30, prev.get("resp_rate_bpm", 16) + random.choice([-1, 0, 1])))

                    if hr < 50: alarms.append("HR LOW (BRADYCARDIA)")
                    elif hr > 120: alarms.append("HR HIGH (TACHYCARDIA)")
                    if spo2 < 90: alarms.append("SpO2 CRITICAL DESAT")
                    if temp >= 38.5: alarms.append("HYPERTHERMIA HIGH TEMP")

                    payload = {
                        "device_id": dev_id,
                        "device_type": dtype,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "active_alarms": alarms,
                        "vitals": {
                            "heart_rate_bpm": hr,
                            "spo2_pct": spo2,
                            "nibp_systolic": sys,
                            "nibp_diastolic": dia,
                            "resp_rate_bpm": resp,
                            "temp_c": temp
                        }
                    }

                elif dtype == "DIALYSIS":
                    prev = LIVE_DEVICE_STATE.get(dev_id, {}).get("dialysis_metrics", {})
                    bfr = prev.get("blood_flow_ml_min", 250) + random.choice([-5, 0, 5])
                    ufr = prev.get("uf_rate_ml_hr", 300)
                    total_uf = prev.get("total_uf_removed_ml", 1200) + random.randint(1, 3)
                    vp = prev.get("venous_pressure_mmhg", 110) + random.choice([-3, -1, 1, 3])

                    if vp > 180: alarms.append("VENOUS PRESSURE HIGH")
                    if bfr < 150: alarms.append("BLOOD FLOW RESTRICTED")

                    payload = {
                        "device_id": dev_id,
                        "device_type": dtype,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "active_alarms": alarms,
                        "dialysis_metrics": {
                            "blood_flow_ml_min": bfr,
                            "uf_rate_ml_hr": ufr,
                            "total_uf_removed_ml": total_uf,
                            "venous_pressure_mmhg": vp,
                            "dialysate_temp_c": 36.5
                        }
                    }

                else:  # SYRINGE_PUMP
                    prev = LIVE_DEVICE_STATE.get(dev_id, {}).get("infusion_status", {})
                    rate = prev.get("rate_ml_hr", 5.0)
                    vol = round(prev.get("volume_infused_ml", 8.5) + (rate / 3600.0) * 1.5, 2)
                    raw_p = max(20.0, min(140.0, prev.get("pressure_kpa", 38.0) + random.choice([-2.0, -1.0, 0.5, 1.5, 3.0])))
                    pressure = round(raw_p, 1)

                    if pressure > 100.0: alarms.append("OCCLUSION DOWNSTREAM - HIGH PRESSURE")
                    if vol >= 50.0: alarms.append("VTBI INFUSION COMPLETE")

                    payload = {
                        "device_id": dev_id,
                        "device_type": "SYRINGE_PUMP",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "active_alarms": alarms,
                        "ders": {"drug_name": "Norepinephrine"},
                        "infusion_status": {
                            "rate_ml_hr": rate,
                            "vtbi_ml": 50.0,
                            "volume_infused_ml": vol,
                            "time_remaining_sec": max(0, int((50.0 - vol) / max(0.1, rate) * 3600)),
                            "pressure_kpa": pressure
                        }
                    }

                LIVE_DEVICE_STATE[dev_id] = payload

                # Broadcast live frames to connected web clients
                dead_ws = set()
                msg = json.dumps(payload)
                for ws in list(connected_websockets):
                    try:
                        await ws.send_text(msg)
                    except Exception:
                        dead_ws.add(ws)
                connected_websockets.difference_update(dead_ws)

            db.close()
        except Exception as e:
            print(f"[!] Simulation tick notice: {e}")
        await asyncio.sleep(1.5)

@app.on_event("startup")
async def startup_event():
    run_db_migrations()
    start_mqtt_worker()
    asyncio.create_task(telemetry_simulation_loop())

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
    device_type: str

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
    """Fetch active beds and calculate the lowest free bed, MRN, and hardware IDs."""
    try:
        all_active_admissions = (
            db.query(Admission)
            .filter(Admission.status == "ADMITTED")
            .order_by(Admission.admitted_at.desc())
            .all()
        )

        seen_beds = set()
        occupied_bed_numbers = set()
        active_patient_mrns = set()
        unique_admissions = []

        for adm in all_active_admissions:
            bed = db.query(Bed).filter((Bed.bed_id == adm.bed_id) | (Bed.bed_number == adm.bed_id)).first()
            bed_num = bed.bed_number if bed else adm.bed_id

            if bed_num in seen_beds or adm.patient_id in active_patient_mrns:
                adm.status = "DISCHARGED"
                adm.discharged_at = datetime.now(timezone.utc)
                adm.discharge_type = "Duplicate Cleanup"
                continue

            seen_beds.add(bed_num)
            occupied_bed_numbers.add(bed_num)
            active_patient_mrns.add(adm.patient_id)
            unique_admissions.append((adm, bed_num))

        db.commit()

        # Query all active hardware
        active_associations = (
            db.query(DeviceAssociation)
            .filter(DeviceAssociation.unpaired_at.is_(None))
            .all()
        )
        busy_device_ids = {a.pump_id for a in active_associations}

        bed_list = []
        for adm, bed_num in unique_admissions:
            patient = db.query(Patient).filter(Patient.patient_id == adm.patient_id).first()
            active_devices = [a for a in active_associations if a.admission_id == adm.admission_id]

            dev_list = []
            for d in active_devices:
                dtype = getattr(d, "device_type", None) or (
                    "PATIENT_MONITOR" if "PM" in d.pump_id else ("DIALYSIS" if "DL" in d.pump_id else "SYRINGE_PUMP")
                )
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

        def bed_sort_key(item):
            digits = re.findall(r'\d+', item['bed_number'])
            return int(digits[0]) if digits else 9999
        bed_list.sort(key=bed_sort_key)

        # 1. Lowest available Bed (1, 2, 3...)
        occupied_indices = set()
        for b_str in occupied_bed_numbers:
            digits = re.findall(r'\d+', b_str)
            if digits:
                occupied_indices.add(int(digits[0]))

        lowest_free_idx = 1
        while lowest_free_idx in occupied_indices:
            lowest_free_idx += 1
        next_available_bed = f"ICU-B{lowest_free_idx}"

        # 2. Lowest available Patient MRN
        all_patients = db.query(Patient.patient_id).all()
        all_patient_indices = set()
        for (pid,) in all_patients:
            digits = re.findall(r'\d+', pid)
            if digits:
                all_patient_indices.add(int(digits[0]))

        lowest_mrn_idx = 1
        while (lowest_mrn_idx in all_patient_indices) or (f"PTN-{str(lowest_mrn_idx).zfill(6)}" in active_patient_mrns):
            lowest_mrn_idx += 1
        next_mrn = f"PTN-{str(lowest_mrn_idx).zfill(6)}"

        # 3. Lowest available Hardware from Predefined Fleet Pools
        suggested_sp = next((sp for sp in FLEET_SP if sp not in busy_device_ids), "SP01-2026-0001")
        suggested_pm = next((pm for pm in FLEET_PM if pm not in busy_device_ids), "PM01-2026-1001")
        suggested_dl = next((dl for dl in FLEET_DL if dl not in busy_device_ids), "DL01-2026-5001")

        return {
            "active_associations": bed_list,
            "beds": bed_list,
            "next_suggestions": {
                "bed": next_available_bed,
                "mrn": next_mrn,
                "sp": suggested_sp,
                "pm": suggested_pm,
                "dl": suggested_dl
            }
        }
    except Exception as e:
        print(f"[!] Registry error: {e}")
        return {
            "active_associations": [],
            "beds": [],
            "next_suggestions": {
                "bed": "ICU-B1",
                "mrn": "PTN-000001",
                "sp": "SP01-2026-0001",
                "pm": "PM01-2026-1001",
                "dl": "DL01-2026-5001"
            }
        }

@app.post("/api/v1/admit-patient")
def admit_patient(req: AdmitPatientRequest, db: Session = Depends(get_db)):
    """Blocks duplicate beds and duplicate patient MRNs."""
    try:
        now = datetime.now(timezone.utc)

        # Rule 1: Bed occupied?
        if db.query(Admission).filter(Admission.bed_id == req.bed_number, Admission.status == "ADMITTED").first():
            raise HTTPException(status_code=400, detail=f"Bed Station '{req.bed_number}' is already occupied!")

        # Rule 2: Patient MRN already admitted?
        if db.query(Admission).filter(Admission.patient_id == req.patient_mrn, Admission.status == "ADMITTED").first():
            raise HTTPException(status_code=400, detail=f"Patient with MRN '{req.patient_mrn}' is currently already admitted!")

        # Upsert Bed
        bed = db.query(Bed).filter((Bed.bed_id == req.bed_number) | (Bed.bed_number == req.bed_number)).first()
        if not bed:
            bed = Bed(bed_id=req.bed_number, ward_id="icu-ward-a", bed_number=req.bed_number, current_status="OCCUPIED")
            db.add(bed)
            db.flush()
        else:
            bed.current_status = "OCCUPIED"

        # Upsert Patient
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
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/devices/attach")
def attach_device_to_bed(req: AttachDeviceRequest, db: Session = Depends(get_db)):
    """Attaches a device from the fleet."""
    try:
        now = datetime.now(timezone.utc)

        existing = db.query(DeviceAssociation).filter(
            DeviceAssociation.pump_id == req.device_id,
            DeviceAssociation.unpaired_at.is_(None)
        ).first()

        if existing:
            raise HTTPException(status_code=400, detail=f"Device '{req.device_id}' is already in active use!")

        bed = db.query(Bed).filter((Bed.bed_id == req.bed_number) | (Bed.bed_number == req.bed_number)).first()
        bed_id = bed.bed_id if bed else req.bed_number
        adm = db.query(Admission).filter(
            Admission.bed_id == bed_id,
            Admission.status == "ADMITTED"
        ).order_by(Admission.admitted_at.desc()).first()

        if not adm:
            raise HTTPException(status_code=404, detail=f"No active admitted patient found at bed {req.bed_number}")

        pump_rec = db.query(Pump).filter(Pump.pump_id == req.device_id).first()
        if not pump_rec:
            pump_rec = Pump(pump_id=req.device_id, model_name=req.device_type, firmware_version="v2.1.0", status="ONLINE")
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
        return {"status": "success", "message": f"Device {req.device_id} returned to available inventory."}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/discharge-encounter")
def discharge_encounter(req: DischargeEncounterRequest, db: Session = Depends(get_db)):
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

            # Return all attached devices to the available pool
            active_devices = db.query(DeviceAssociation).filter(
                DeviceAssociation.admission_id == adm.admission_id,
                DeviceAssociation.unpaired_at.is_(None)
            ).all()

            for d in active_devices:
                d.unpaired_at = now

        if bed:
            bed.current_status = "AVAILABLE"

        db.commit()
        return {"status": "success", "message": f"Bed {req.bed_number} discharged and all hardware returned to pool."}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

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

        admission = db.query(Admission).filter(
            Admission.patient_id == patient_id
        ).order_by(Admission.admitted_at.desc()).first()

        reports = db.query(DiagnosticReport).filter(
            DiagnosticReport.patient_id == patient_id
        ).order_by(DiagnosticReport.created_at.desc()).all()

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
            "total_reports": len(reports_list),
            "reports": reports_list
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/v1/discharged-records")
def get_discharged_records(db: Session = Depends(get_db)):
    try:
        admissions = db.query(Admission).filter(
            Admission.status == "DISCHARGED"
        ).order_by(Admission.discharged_at.desc()).all()

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
        return []

@app.websocket("/ws/telemetry")
async def websocket_telemetry_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected_websockets.add(websocket)
    try:
        while True:
            await asyncio.sleep(1)
    except Exception:
        pass
    finally:
        connected_websockets.discard(websocket)
