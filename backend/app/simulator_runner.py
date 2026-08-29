import os
import json
import time
import random
import threading
import paho.mqtt.client as mqtt

MQTT_BROKER = os.getenv("MQTT_BROKER_URL", "broker.emqx.io")
MQTT_PORT = int(os.getenv("MQTT_BROKER_PORT", "1883"))

# Simulated active fleet
PUMPS_SIMULATION_CONFIG = [
    {
        "pump_id": "SP01-2026-0001",
        "ward": "icu-ward-a",
        "drug": "Norepinephrine",
        "base_rate": 5.0,
        "vtbi": 50.0,
        "volume_delivered": 14.2,
        "base_pressure": 42.0,
        "battery_pct": 94,
        "force_alarm": False
    },
    {
        "pump_id": "SP01-2026-0004",
        "ward": "icu-ward-a",
        "drug": "Propofol 1%",
        "base_rate": 25.0,
        "vtbi": 100.0,
        "volume_delivered": 68.0,
        "base_pressure": 38.0,
        "battery_pct": 88,
        "force_alarm": False
    },
    {
        "pump_id": "SP01-2026-0003",
        "ward": "icu-ward-a",
        "drug": "Fentanyl",
        "base_rate": 2.0,
        "vtbi": 50.0,
        "volume_delivered": 12.0,
        "base_pressure": 40.0,
        "battery_pct": 98,
        "force_alarm": False
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
        "force_alarm": False
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

    while True:
        try:
            for pump in PUMPS_SIMULATION_CONFIG:
                # 1. Increment delivery volume progressively (rate mL/hr -> delivered mL per second)
                step_vol = pump["base_rate"] / 3600.0
                pump["volume_delivered"] += step_vol
                if pump["volume_delivered"] >= pump["vtbi"]:
                    pump["volume_delivered"] = 0.5  # Reset loop for demo continuity

                # 2. Dynamic pressure fluctuations
                pressure_fluctuation = random.uniform(-1.2, 1.5)
                current_pressure = round(pump["base_pressure"] + pressure_fluctuation, 1)

                # 3. Calculate remaining time
                remaining_vol = max(0.0, pump["vtbi"] - pump["volume_delivered"])
                time_remaining_sec = int((remaining_vol / pump["base_rate"]) * 3600) if pump["base_rate"] > 0 else 0

                # Check alarms
                alarms = []
                if pump.get("force_alarm") or current_pressure > 100.0:
                    alarms.append("OCCLUSION_DOWNSTREAM")
                    alarms.append("PRESSURE_HIGH")

                payload = {
                    "pump_id": pump["pump_id"],
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "infusion_status": {
                        "state": "INFUSING",
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

            time.sleep(1)  # Broadcast telemetry stream once every second
        except Exception as err:
            print(f"[!] Error in Cloud Telemetry Generator: {err}")
            time.sleep(2)

def start_cloud_simulator():
    sim_thread = threading.Thread(target=simulation_loop, daemon=True, name="AutonomousSimulatorThread")
    sim_thread.start()
    print("[*] Cloud Autonomous Syringe Pump Telemetry Generator running in background.")
