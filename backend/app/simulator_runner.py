import os
import json
import time
import random
import threading
import paho.mqtt.client as mqtt

MQTT_BROKER = os.getenv("MQTT_BROKER_URL", "broker.emqx.io")
MQTT_PORT = int(os.getenv("MQTT_BROKER_PORT", "1883"))

# Active simulation fleet config
PUMPS_SIMULATION_CONFIG = [
    {
        "pump_id": "SP01-2026-0001",
        "ward": "icu-ward-a",
        "drug": "Norepinephrine",
        "base_rate": 5.0,
        "vtbi": 50.0,
        "volume_delivered": 14.2,
        "base_pressure": 40.0,
        "battery_pct": 94,
    },
    {
        "pump_id": "SP01-2026-0002",
        "ward": "icu-ward-a",
        "drug": "Insulin Regular",
        "base_rate": 3.5,
        "vtbi": 100.0,
        "volume_delivered": 22.4,
        "base_pressure": 35.0,
        "battery_pct": 91,
    },
    {
        "pump_id": "SP01-2026-0003",
        "ward": "icu-ward-a",
        "drug": "Fentanyl",
        "base_rate": 2.0,
        "vtbi": 50.0,
        "volume_delivered": 12.0,
        "base_pressure": 38.0,
        "battery_pct": 98,
    },
    {
        "pump_id": "SP01-2026-0004",
        "ward": "icu-ward-a",
        "drug": "Propofol 1%",
        "base_rate": 25.0,
        "vtbi": 100.0,
        "volume_delivered": 68.0,
        "base_pressure": 36.0,
        "battery_pct": 88,
    }
]

def simulation_loop():
    time.sleep(3)  # Wait for main FastAPI and MQTT daemon to fully initialize
    client = mqtt.Client(client_id="cloud_autonomous_simulator_fleet")
    
    try:
        print(f"[*] Cloud Simulator connecting to MQTT Broker: {MQTT_BROKER}:{MQTT_PORT}...")
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        client.loop_start()
    except Exception as e:
        print(f"[!] Cloud Simulator MQTT connect warning: {e}")
        return

    # Random anomaly tracking
    active_alarm_pump = None
    next_event_time = time.time() + 10  # First event triggers after 10s
    alarm_duration_end = 0

    while True:
        try:
            current_time = time.time()

            # Manage Random Alarm Lifecycle
            if active_alarm_pump is None and current_time >= next_event_time:
                # 70% chance to trigger an alarm on a random pump, 30% chance of an extended all-clear period
                if random.random() < 0.70:
                    chosen_pump = random.choice(PUMPS_SIMULATION_CONFIG)
                    active_alarm_pump = chosen_pump["pump_id"]
                    alarm_duration_end = current_time + random.randint(10, 18)  # Alarm lasts 10 to 18 seconds
                else:
                    next_event_time = current_time + random.randint(15, 25)

            elif active_alarm_pump and current_time >= alarm_duration_end:
                # Clear the alarm and return ward to completely normal state
                active_alarm_pump = None
                next_event_time = current_time + random.randint(15, 30)  # Next event in 15-30s

            for pump in PUMPS_SIMULATION_CONFIG:
                # 1. Increment volume delivered progressively
                step_vol = pump["base_rate"] / 3600.0
                pump["volume_delivered"] += step_vol
                if pump["volume_delivered"] >= pump["vtbi"]:
                    pump["volume_delivered"] = 0.5

                # 2. Dynamic pressure simulation
                alarms = []
                if pump["pump_id"] == active_alarm_pump:
                    # Random Occlusion Spike (106.0 kPa to 124.0 kPa)
                    current_pressure = round(110.0 + random.uniform(-3.5, 12.0), 1)
                    alarms.append("OCCLUSION_DOWNSTREAM")
                    alarms.append("PRESSURE_HIGH")
                else:
                    # Normal physiological pressure range (32.0 kPa to 44.0 kPa)
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

            time.sleep(1)  # Broadcast telemetry stream every second
        except Exception as err:
            print(f"[!] Error in Cloud Telemetry Generator: {err}")
            time.sleep(2)

def start_cloud_simulator():
    sim_thread = threading.Thread(target=simulation_loop, daemon=True, name="AutonomousSimulatorThread")
    sim_thread.start()
    print("[*] Cloud Autonomous Syringe Pump Telemetry Generator running in background.")
