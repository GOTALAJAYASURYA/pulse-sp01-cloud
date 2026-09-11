import os
import json
import time
import threading
import random
from datetime import datetime, timezone
import redis

def telemetry_simulator_loop():
    """Generates realistic live telemetry for PM, SP, and Dialysis machines."""
    redis_url = os.getenv("REDIS_URL") or os.getenv("REDIS_HOST")
    r = None

    if redis_url and redis_url != "localhost":
        try:
            if redis_url.startswith("redis://") or redis_url.startswith("rediss://"):
                r = redis.from_url(redis_url)
            else:
                r = redis.Redis(host=redis_url, port=int(os.getenv("REDIS_PORT", "6379")), db=0)
        except Exception:
            r = None

    while True:
        try:
            # 1. Patient Monitor (PM) frame
            pm_frame = {
                "device_id": "PM-2026-0001",
                "device_type": "PATIENT_MONITOR",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "vitals": {
                    "heart_rate_bpm": random.randint(72, 82),
                    "spo2_pct": random.randint(98, 100),
                    "nibp_systolic": random.randint(118, 126),
                    "nibp_diastolic": random.randint(76, 82),
                    "resp_rate_bpm": random.randint(14, 18),
                    "temp_c": round(random.uniform(36.6, 37.1), 1)
                },
                "active_alarms": []
            }

            # 2. Syringe Pump (SP) frame
            sp_frame = {
                "device_id": "SP01-2026-0001",
                "device_type": "SYRINGE_PUMP",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "ders": {"drug_name": "Norepinephrine"},
                "infusion_status": {
                    "rate_ml_hr": 5.0,
                    "vtbi_ml": 50.0,
                    "volume_infused_ml": round(12.4 + (time.time() % 100) * 0.05, 1),
                    "time_remaining_sec": 24800,
                    "pressure_kpa": round(random.uniform(37.5, 42.0), 1)
                },
                "active_alarms": []
            }

            # 3. Dialysis Machine (DL) frame
            dl_frame = {
                "device_id": "DL-2026-0001",
                "device_type": "DIALYSIS",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "dialysis_metrics": {
                    "blood_flow_ml_min": random.randint(245, 255),
                    "uf_rate_ml_hr": 300,
                    "total_uf_removed_ml": 1250,
                    "venous_pressure_mmhg": random.randint(105, 115),
                    "dialysate_temp_c": 36.5
                },
                "active_alarms": []
            }

            if r:
                r.publish("channel:telemetry", json.dumps(pm_frame))
                r.publish("channel:telemetry", json.dumps(sp_frame))
                r.publish("channel:telemetry", json.dumps(dl_frame))

        except Exception as err:
            pass

        time.sleep(1.0)

def start_cloud_simulator():
    sim_thread = threading.Thread(target=telemetry_simulator_loop, daemon=True)
    sim_thread.start()
