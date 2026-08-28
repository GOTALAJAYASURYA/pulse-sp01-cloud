import os
import json
import redis
import paho.mqtt.client as mqtt
from app.core.database import SessionLocal
from app.models.models import PumpTelemetryLog, DeviceAssociation

# Read Redis configuration with cloud fallback
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
if REDIS_HOST.startswith("redis://"):
    r = redis.Redis.from_url(REDIS_HOST)
else:
    r = redis.Redis(host=REDIS_HOST, port=int(os.getenv("REDIS_PORT", "6379")), db=0)

# Read public/cloud MQTT broker configuration
MQTT_BROKER = os.getenv("MQTT_BROKER_URL", "broker.emqx.io")
MQTT_PORT = int(os.getenv("MQTT_BROKER_PORT", "1883"))

def on_connect(client, userdata, flags, rc):
    print(f"[*] MQTT Ingestion Daemon connected to broker {MQTT_BROKER} (code {rc})")
    client.subscribe("hospitals/+/wards/+/pumps/+/telemetry")

def on_message(client, userdata, msg):
    try:
        data = json.loads(msg.payload.decode())
        pump_id = data.get("pump_id")
        
        # 1. Update quick-access cache in Redis (TTL: 60s)
        try:
            r.setex(f"live:pump:{pump_id}", 60, json.dumps(data))
            r.publish("channel:telemetry", json.dumps(data))
        except Exception as r_err:
            print(f"[!] Redis error: {r_err}")

        # 2. Persist telemetry record into PostgreSQL
        db = SessionLocal()
        try:
            assoc = db.query(DeviceAssociation).filter(
                DeviceAssociation.pump_id == pump_id,
                DeviceAssociation.unpaired_at.is_(None)
            ).first()

            session_id = assoc.admission_id if assoc else None

            log_entry = PumpTelemetryLog(
                recorded_at=data["timestamp"],
                pump_id=pump_id,
                session_id=session_id,
                current_rate_ml_hr=data["infusion_status"]["rate_ml_hr"],
                volume_infused_ml=data["infusion_status"]["volume_infused_ml"],
                pressure_kpa=data["infusion_status"]["pressure_kpa"],
                battery_pct=data["battery"]["level_pct"],
                alarms=data.get("active_alarms", [])
            )
            db.add(log_entry)
            db.commit()
        except Exception as db_err:
            db.rollback()
            try:
                log_entry.session_id = None
                db.add(log_entry)
                db.commit()
            except Exception:
                db.rollback()
        finally:
            db.close()

    except Exception as e:
        print(f"[!] Ingestion Error: {e}")

def start_mqtt_worker():
    try:
        client = mqtt.Client(client_id=f"render_fastapi_{os.getenv('RENDER_SERVICE_ID', 'daemon')}")
        client.on_connect = on_connect
        client.on_message = on_message
        print(f"[*] Connecting MQTT worker to {MQTT_BROKER}:{MQTT_PORT}...")
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        client.loop_start()
    except Exception as e:
        print(f"[!] Warning: Could not connect to MQTT broker ({e}). Worker will retry when available.")
