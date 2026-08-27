import time
import json
import uuid
import random
from datetime import datetime, timezone
import requests
import paho.mqtt.client as mqtt

BROKER = "localhost"
PORT = 1883
HOSPITAL_ID = "hosp-001"
WARD_ID = "icu-ward-a"
API_URL = "http://localhost:8000/api/v1/registry-status"

# Clinical Drug & Profile Presets for diverse patients
DRUG_PRESETS = [
    {"drug": "Norepinephrine", "rate": 5.0, "vtbi": 50.0, "unit": "mcg/kg/min", "dose": "0.10", "alarm_cycle": True},
    {"drug": "Propofol 1%", "rate": 25.0, "vtbi": 100.0, "unit": "mg/kg/hr", "dose": "2.5", "alarm_cycle": False},
    {"drug": "Fentanyl", "rate": 2.0, "vtbi": 50.0, "unit": "mcg/hr", "dose": "50.0", "alarm_cycle": False},
    {"drug": "Regular Insulin", "rate": 4.5, "vtbi": 100.0, "unit": "units/hr", "dose": "4.5", "alarm_cycle": False},
    {"drug": "Midazolam", "rate": 3.0, "vtbi": 50.0, "unit": "mg/hr", "dose": "3.0", "alarm_cycle": False},
    {"drug": "Dopamine", "rate": 8.0, "vtbi": 100.0, "unit": "mcg/kg/min", "dose": "5.0", "alarm_cycle": False},
]

client = mqtt.Client(client_id="pulse_fleet_master_simulator")
client.connect(BROKER, PORT, 60)
client.loop_start()

# State tracker for volume delivered and cycle counters per active pump
pump_state = {}

print("[*] Starting Pulse SP-01 Dynamic Fleet Telemetry Engine...")
print("[*] Listening for all active database associations in real-time...\n")

cycle_tick = 0

try:
    while True:
        cycle_tick += 1
        
        # 1. Fetch currently active pumps dynamically from backend
        try:
            res = requests.get(API_URL, timeout=1.5)
            if res.status_code == 200:
                active_assocs = res.json().get("active_associations", [])
            else:
                active_assocs = []
        except Exception:
            active_assocs = []

        # Fallback to default pump if no beds are paired yet
        if not active_assocs:
            active_assocs = [{
                "pump_id": "SP01-2026-0001",
                "bed_number": "ICU-B1",
                "patient_name": "Johnathan Doe"
            }]

        for idx, assoc in enumerate(active_assocs):
            pump_id = assoc["pump_id"]
            bed_no = assoc.get("bed_number", "ICU-B1")
            
            # Pick a deterministic clinical profile based on pump index
            preset = DRUG_PRESETS[idx % len(DRUG_PRESETS)]

            # Initialize state if newly paired
            if pump_id not in pump_state:
                pump_state[pump_id] = {
                    "delivered": round(random.uniform(5.0, 18.0), 1),
                    "counter": 0
                }

            state_data = pump_state[pump_id]
            state_data["counter"] += 1

            # Alarm behavior: first pump alternates every 10s for alarm demonstration
            is_alarm = preset["alarm_cycle"] and ((state_data["counter"] % 10) >= 5)

            if is_alarm:
                current_rate = 0.0
                pressure = 118.5
                alarms = ["OCCLUSION_DOWNSTREAM", "PRESSURE_HIGH"]
                infusion_state = "ALARM_STOPPED"
            else:
                current_rate = preset["rate"]
                state_data["delivered"] = round(state_data["delivered"] + (current_rate / 3600.0) * 2, 2)
                pressure = round(34.0 + (state_data["counter"] % 6) * 1.4 + (idx * 2.1), 1)
                alarms = []
                infusion_state = "INFUSING"

            vtbi = preset["vtbi"]
            rem_time = int(((vtbi - state_data["delivered"]) / current_rate) * 3600) if current_rate > 0 else 0

            payload = {
                "protocol_version": "1.0",
                "msg_id": str(uuid.uuid4()),
                "pump_id": pump_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "battery": {"level_pct": max(45, 98 - (idx * 8)), "mains_connected": True},
                "infusion_status": {
                    "state": infusion_state,
                    "syringe_brand": "BD_PLASTIPAK",
                    "syringe_size_ml": 50,
                    "rate_ml_hr": current_rate,
                    "vtbi_ml": vtbi,
                    "volume_infused_ml": state_data["delivered"],
                    "time_remaining_sec": max(0, rem_time),
                    "pressure_kpa": pressure,
                    "occlusion_limit_kpa": 100.0,
                    "kvo_active": False
                },
                "ders": {
                    "drug_name": preset["drug"],
                    "concentration": "Standard",
                    "dose_rate": preset["dose"],
                    "dose_unit": preset["unit"]
                },
                "active_alarms": alarms
            }

            topic = f"hospitals/{HOSPITAL_ID}/wards/{WARD_ID}/pumps/{pump_id}/telemetry"
            client.publish(topic, json.dumps(payload), qos=1)

            status_str = f"ALARM: {alarms}" if alarms else f"Rate: {current_rate} mL/h | Pres: {pressure} kPa"
            print(f"[{bed_no} | {pump_id}] {preset['drug']} -> {status_str}")

        time.sleep(2)

except KeyboardInterrupt:
    print("\nStopping Fleet Simulator...")
    client.loop_stop()
    client.disconnect()