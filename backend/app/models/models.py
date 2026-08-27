from sqlalchemy import Column, String, Numeric, SmallInteger, JSON, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime, timezone
import uuid
from app.core.database import Base

class Ward(Base):
    __tablename__ = "wards"
    ward_id = Column(String(64), primary_key=True)
    name = Column(String(100), nullable=False)
    ward_type = Column(String(50), default="ICU")

class Bed(Base):
    __tablename__ = "beds"
    bed_id = Column(String(64), primary_key=True)
    ward_id = Column(String(64), ForeignKey("wards.ward_id", ondelete="CASCADE"))
    bed_number = Column(String(50), unique=True, nullable=False)
    current_status = Column(String(20), default="AVAILABLE")

class Pump(Base):
    __tablename__ = "pumps"
    pump_id = Column(String(64), primary_key=True)
    model_name = Column(String(50), default="Pulse SP-01")
    firmware_version = Column(String(30), nullable=False)
    status = Column(String(30), default="ONLINE")
    last_heartbeat = Column(DateTime(timezone=True))

class Patient(Base):
    __tablename__ = "patients"
    patient_id = Column(String(64), primary_key=True)
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)

class Admission(Base):
    __tablename__ = "admissions"
    admission_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id = Column(String(64), ForeignKey("patients.patient_id"))
    bed_id = Column(String(64), ForeignKey("beds.bed_id"))
    primary_diagnosis = Column(String, nullable=False)
    admitted_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    status = Column(String(20), default="ADMITTED")

class DeviceAssociation(Base):
    __tablename__ = "device_associations"
    association_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    admission_id = Column(UUID(as_uuid=True), ForeignKey("admissions.admission_id"))
    bed_id = Column(String(64), ForeignKey("beds.bed_id"))
    pump_id = Column(String(64), ForeignKey("pumps.pump_id"))
    paired_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    unpaired_at = Column(DateTime(timezone=True), nullable=True)
    paired_by_user_id = Column(String(64), nullable=False)

class PumpTelemetryLog(Base):
    __tablename__ = "pump_telemetry_logs"
    recorded_at = Column(DateTime(timezone=True), primary_key=True)
    pump_id = Column(String(64), primary_key=True)
    session_id = Column(UUID(as_uuid=True), nullable=True)
    current_rate_ml_hr = Column(Numeric(6, 2))
    volume_infused_ml = Column(Numeric(6, 2))
    pressure_kpa = Column(Numeric(6, 2))
    battery_pct = Column(SmallInteger)
    alarms = Column(JSON, default=list)