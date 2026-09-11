import threading
import time
import json
import random
import os
from datetime import datetime, timezone
import redis
from app.core.database import SessionLocal
from app.models.models import DeviceAssociation

def get_redis_client():
    redis_url = os.getenv("REDIS_URL") or os.getenv("REDIS_HOST")
    if redis_url and redis_url != "localhost":
        try:
            return redis.from_url(redis_url) if redis_url.startswith("redis") else redis.Redis(host=redis_url, port=6379, db=0)
        except Exception:
            return None
    return None

def simulation_worker():
    print("[*] Multi-Device Telemetry Simulator active (PM, SP, Dialysis)...")
    r = get_redis_client()

    while True:
        try:
            db = SessionLocal()
            active_assocs = db.query(DeviceAssociation).filter(DeviceAssociation.unpaired_at.is_(None)).all()

            for assoc in active_assocs:
                device_id = assoc.device_id
                dtype = assoc.device_type

                payload = {
                    "device_id": device_id,
                    "device_type": dtype,
                    "bed_number": assoc.bed_id,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }

                if dtype == "PATIENT_MONITOR":
                    payload["vitals"] = {
                        "heart_rate": random.randint(72, 85),
                        "spo2": random.randint(97, 100),
                        "nibp_systolic": random.randint(118, 126),
                        "nibp_diastolic": random.randint(76, 82),
                        "resp_rate": random.randint(14, 18),
                        "temp_c": round(random.uniform(36.6, 37.1), 1)
                    }
                    payload["active_alarms"] = []

                elif dtype == "DIALYSIS":
                    payload["dialysis_metrics"] = {
                        "blood_flow_rate": 250, # mL/min
                        "uf_rate": 300, # mL/h
                        "uf_removed_ml": round(random.uniform(650, 1400), 1),
                        "venous_pressure": random.randint(95, 120), # mmHg
                        "dialysate_temp": 36.5
                    }
                    payload["active_alarms"] = []

                else: # SYRINGE_PUMP
                    payload["infusion_status"] = {
                        "rate_ml_hr": 5.0,
                        "volume_infused_ml": round(random.uniform(12.0, 35.0), 1),
                        "vtbi_ml": 50.0,
                        "pressure_kpa": round(random.uniform(34.0, 42.0), 1),
                        "time_remaining_sec": 3600
                    }
                    payload["ders"] = {"drug_name": "Norepinephrine"}
                    payload["active_alarms"] = []

                if r:
                    r.publish("channel:telemetry", json.dumps(payload))

            db.close()
        except Exception as e:
            print(f"[!] Simulator tick error: {e}")

        time.sleep(1.0)

def start_multi_device_simulator():
    t = threading.Thread(target=simulation_worker, daemon=True)
    t.start()
