import json
import redis
import paho.mqtt.client as mqtt
from app.core.database import SessionLocal
from app.models.models import PumpTelemetryLog, DeviceAssociation

r = redis.Redis(host='localhost', port=6379, db=0)

def on_connect(client, userdata, flags, rc):
    print(f"[*] MQTT Ingestion Daemon connected to broker (code {rc})")
    client.subscribe("hospitals/+/wards/+/pumps/+/telemetry")

def on_message(client, userdata, msg):
    try:
        data = json.loads(msg.payload.decode())
        pump_id = data.get("pump_id")
        
        # 1. Update quick-access cache in Redis (TTL: 60s)
        r.setex(f"live:pump:{pump_id}", 60, json.dumps(data))
        
        # 2. Publish to Redis Pub/Sub for WebSockets (powers the live UI)
        r.publish("channel:telemetry", json.dumps(data))

        # 3. Safely persist telemetry record into TimescaleDB
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
            # If session_id caused a foreign key violation, insert with session_id=None
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
    client = mqtt.Client(client_id="fastapi_mqtt_ingestor")
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect("localhost", 1883, 60)
    client.loop_start()