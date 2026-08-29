import os
import json
import time
import random
import threading
import paho.mqtt.client as mqtt
from app.core.database import SessionLocal
from app.models.models import DeviceAssociation

MQTT_BROKER = os.getenv("MQTT_BROKER_URL", "broker.emqx.io")
MQTT_PORT = int(os.getenv("MQTT_BROKER_PORT", "1883"))

# Clinical drug library for dynamic assignments
DRUG_LIBRARY = [
    {"drug": "Norepinephrine", "rate": 5.0, "vtbi": 50.0, "base_p": 40.0},
    {"drug": "Propofol 1%", "rate": 25.0, "vtbi": 100.0, "base_p": 36.0},
    {"drug": "Fentanyl", "rate": 2.0, "vtbi": 50.0, "base_p": 38.0},
    {"drug": "Insulin Regular", "rate": 3.5, "vtbi": 100.0, "base_p": 35.0},
    {"drug": "Dopamine", "rate": 10.0, "vtbi": 200.0, "base_p": 42.0},
    {"drug": "Midazolam", "rate": 4.0, "vtbi": 50.0, "base_p": 37.0},
    {"drug": "Vasopressin", "rate": 2.4, "vtbi": 50.0, "base_p": 39.0}
]

# Track live simulation state per pump across iterations
pump_states = {}

def get_active_pumps_from_db():
    """Dynamically fetch all currently active paired pumps from database."""
    db = SessionLocal()
    try:
        active = (
            db.query(DeviceAssociation.pump_id)
            .filter(DeviceAssociation.unpaired_at.is_(None))
            .all()
        )
        return [row[0] for row in active]
    except Exception as e:
        return []
    finally:
        db.close()

def simulation_loop():
    time.sleep(3)
    client = mqtt.Client(client_id="cloud_autonomous_simulator_fleet")
    
    try:
        print(f"[*] Dynamic Cloud Simulator connecting to MQTT Broker: {MQTT_BROKER}:{MQTT_PORT}...")
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        client.loop_start()
    except Exception as e:
        print(f"[!] Dynamic Simulator MQTT connect warning: {e}")
        return

    active_alarm_pump = None
    next_event_time = time.time() + 10
    alarm_duration_end = 0

    while True:
        try:
            current_time = time.time()
            active_pumps = get_active_pumps_from_db()

            # Ensure minimum default pumps are always available for simulation
            if not active_pumps:
                active_pumps = ["SP01-2026-0001", "SP01-2026-0002", "SP01-2026-0003", "SP01-2026-0004"]

            # Initialize state for any newly created pump on the fly
            for p_id in active_pumps:
                if p_id not in pump_states:
                    # Deterministically pick a drug based on pump ID index
                    idx = sum(ord(c) for c in p_id) % len(DRUG_LIBRARY)
                    profile = DRUG_LIBRARY[idx]
                    pump_states[p_id] = {
                        "pump_id": p_id,
                        "ward": "icu-ward-a",
                        "drug": profile["drug"],
                        "base_rate": profile["rate"],
                        "vtbi": profile["vtbi"],
                        "volume_delivered": round(random.uniform(5.0, 15.0), 2),
                        "base_pressure": profile["base_p"],
                        "battery_pct": random.randint(85, 99)
                    }

            # Manage Random Anomaly Lifecycle across all active pumps
            if active_alarm_pump is None and current_time >= next_event_time:
                if random.random() < 0.70 and active_pumps:
                    active_alarm_pump = random.choice(active_pumps)
                    alarm_duration_end = current_time + random.randint(10, 18)
                else:
                    next_event_time = current_time + random.randint(15, 25)

            elif active_alarm_pump and current_time >= alarm_duration_end:
                active_alarm_pump = None
                next_event_time = current_time + random.randint(15, 30)

            # Broadcast live telemetry for EVERY active pump
            for p_id in active_pumps:
                pump = pump_states.get(p_id)
                if not pump:
                    continue

                # 1. Increment delivery volume
                step_vol = pump["base_rate"] / 3600.0
                pump["volume_delivered"] += step_vol
                if pump["volume_delivered"] >= pump["vtbi"]:
                    pump["volume_delivered"] = 0.5

                # 2. Dynamic pressure simulation
                alarms = []
                if p_id == active_alarm_pump:
                    current_pressure = round(110.0 + random.uniform(-3.0, 12.0), 1)
                    alarms.append("OCCLUSION_DOWNSTREAM")
                    alarms.append("PRESSURE_HIGH")
                else:
                    current_pressure = round(pump["base_pressure"] + random.uniform(-2.0, 2.5), 1)

                # 3. Calculate remaining time
                remaining_vol = max(0.0, pump["vtbi"] - pump["volume_delivered"])
                time_remaining_sec = int((remaining_vol / pump["base_rate"]) * 3600) if pump["base_rate"] > 0 else 0

                payload = {
                    "pump_id": pump["pump_id"],
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "infusion_status": {
                        "state": "ALARM" if len(alarms) > 0 else "INFUSING",
                        "rate_ml_hr": pump["base_rate"],
                        "vtbi_ml": pump["vtbi"],
                        "volume_infused_ml": round(pump["volume_delivered"], 2),
                        "time_remaining_sec": time_remaining_sec,
                        "pressure_kpa": current_pressure
                    },
                    "ders": {
                        "drug_name": pump["drug"]
                    },
                    "battery": {
                        "level_pct": pump["battery_pct"],
                        "is_charging": True
                    },
                    "active_alarms": alarms
                }

                topic = f"hospitals/hosp-001/wards/{pump['ward']}/pumps/{pump['pump_id']}/telemetry"
                client.publish(topic, json.dumps(payload))

            time.sleep(1)
        except Exception as err:
            print(f"[!] Error in Dynamic Cloud Telemetry Generator: {err}")
            time.sleep(2)

def start_cloud_simulator():
    sim_thread = threading.Thread(target=simulation_loop, daemon=True, name="DynamicAutonomousSimulatorThread")
    sim_thread.start()
    print("[*] Dynamic Cloud Syringe Pump Telemetry Generator running in background.")
