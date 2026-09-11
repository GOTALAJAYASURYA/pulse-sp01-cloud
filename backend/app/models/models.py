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
    ward_id = Column(String(64), ForeignKey("wards.ward_id", ondelete="CASCADE"))
    bed_number = Column(String(50), unique=True, nullable=False)
    current_status = Column(String(20), default="AVAILABLE")

class Device(Base):
    __tablename__ = "devices"
    device_id = Column(String(64), primary_key=True)
    device_type = Column(String(30), nullable=False)  # 'PATIENT_MONITOR', 'SYRINGE_PUMP', 'DIALYSIS'
    model_name = Column(String(50), default="Pulse Pro Series")
    firmware_version = Column(String(30), default="v2.1.0")
    status = Column(String(30), default="AVAILABLE")
    last_heartbeat = Column(DateTime(timezone=True))

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
    primary_diagnosis = Column(String, default="Clinical Monitoring & Care")
    admission_type = Column(String(50), default="Emergency")
    attending_doctor = Column(String(100), default="Dr. Robert Vance")
    admitted_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    discharge_type = Column(String(50), nullable=True)
    discharged_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(String(20), default="ADMITTED")

class DeviceAssociation(Base):
    __tablename__ = "device_associations"
    association_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    admission_id = Column(UUID(as_uuid=True), ForeignKey("admissions.admission_id"))
    bed_id = Column(String(64), ForeignKey("beds.bed_id"))
    device_id = Column(String(64), ForeignKey("devices.device_id"))
    device_type = Column(String(30), nullable=False)
    paired_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    unpaired_at = Column(DateTime(timezone=True), nullable=True)
    paired_by_user_id = Column(String(64), default="CLINICAL-NURSE-01")

class MultiDeviceTelemetryLog(Base):
    __tablename__ = "multi_device_telemetry_logs"
    recorded_at = Column(DateTime(timezone=True), primary_key=True)
    device_id = Column(String(64), primary_key=True)
    device_type = Column(String(30), nullable=False)
    telemetry_data = Column(JSON, nullable=False)

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
