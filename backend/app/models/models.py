import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Numeric, SmallInteger, Integer, JSON, DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from app.core.database import Base

class Ward(Base):
    __tablename__ = "wards"
    ward_id = Column(String(64), primary_key=True)
    name = Column(String(100), nullable=False)
    ward_type = Column(String(50), default="ICU")

class Bed(Base):
    __tablename__ = "beds"
    bed_id = Column(String(64), primary_key=True)
    ward_id = Column(String(64), ForeignKey("wards.ward_id", ondelete="CASCADE"), nullable=True)
    bed_number = Column(String(50), unique=True, nullable=False)
    current_status = Column(String(20), default="AVAILABLE")

class Pump(Base):
    __tablename__ = "pumps"
    pump_id = Column(String(64), primary_key=True)
    model_name = Column(String(50), default="Pulse SP-01")
    firmware_version = Column(String(30), nullable=False, default="v1.0.4")
    status = Column(String(30), default="ONLINE")
    last_heartbeat = Column(DateTime(timezone=True), nullable=True)

class Patient(Base):
    __tablename__ = "patients"
    patient_id = Column(String(64), primary_key=True)
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), default="")
    age = Column(Integer, nullable=True)
    gender = Column(String(20), default="Male")
    blood_group = Column(String(10), default="O+")
    phone_number = Column(String(25), nullable=True)
    address = Column(Text, nullable=True)

class Admission(Base):
    __tablename__ = "admissions"
    admission_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id = Column(String(64), ForeignKey("patients.patient_id"))
    bed_id = Column(String(64), ForeignKey("beds.bed_id"))
    primary_diagnosis = Column(String, default="Clinical Monitoring & Infusion")
    admission_type = Column(String(50), default="Emergency")
    attending_doctor = Column(String(100), default="Duty Medical Officer")
    admitted_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    discharge_type = Column(String(50), nullable=True)
    discharged_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(String(20), default="ADMITTED")

class DeviceAssociation(Base):
    __tablename__ = "device_associations"
    association_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    admission_id = Column(UUID(as_uuid=True), ForeignKey("admissions.admission_id"), nullable=True)
    bed_id = Column(String(64), ForeignKey("beds.bed_id"), nullable=True)
    pump_id = Column(String(64), nullable=True)  # Maintained for backward compatibility
    device_id = Column(String(64), nullable=True)
    device_type = Column(String(30), default="SYRINGE_PUMP")
    paired_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    unpaired_at = Column(DateTime(timezone=True), nullable=True)
    paired_by_user_id = Column(String(64), default="CLINICAL-NURSE-01")

# Restored: required by app.mqtt.worker and legacy endpoints
class PumpTelemetryLog(Base):
    __tablename__ = "pump_telemetry_logs"
    recorded_at = Column(DateTime(timezone=True), primary_key=True)
    pump_id = Column(String(64), primary_key=True)
    session_id = Column(UUID(as_uuid=True), nullable=True)
    current_rate_ml_hr = Column(Numeric(6, 2), nullable=True)
    volume_infused_ml = Column(Numeric(6, 2), nullable=True)
    pressure_kpa = Column(Numeric(6, 2), nullable=True)
    battery_pct = Column(SmallInteger, nullable=True)
    alarms = Column(JSON, default=list)

class DiagnosticReport(Base):
    __tablename__ = "diagnostic_reports"
    report_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id = Column(String(64), ForeignKey("patients.patient_id"), nullable=False)
    admission_id = Column(UUID(as_uuid=True), ForeignKey("admissions.admission_id"), nullable=True)
    department = Column(String(50), nullable=False)
    test_name = Column(String(100), nullable=False)
    parameters = Column(JSON, nullable=True)
    technician_notes = Column(Text, nullable=True)
    technician_name = Column(String(100), default="Diagnostic Staff")
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
