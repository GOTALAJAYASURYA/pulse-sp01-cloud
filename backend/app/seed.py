from app.core.database import SessionLocal
from app.models.models import Ward, Bed, Pump, Patient, Admission, DeviceAssociation
import uuid

def seed_database():
    db = SessionLocal()
    try:
        # 1. Ward & Bed
        ward = db.query(Ward).filter(Ward.ward_id == "icu-ward-a").first()
        if not ward:
            ward = Ward(ward_id="icu-ward-a", name="Main ICU Wing", ward_type="ICU")
            db.add(ward)
            db.commit()

        bed = db.query(Bed).filter(Bed.bed_id == "ICU-B01").first()
        if not bed:
            bed = Bed(bed_id="ICU-B01", ward_id="icu-ward-a", bed_number="ICU-01", current_status="OCCUPIED")
            db.add(bed)
            db.commit()

        # 2. Syringe Pump
        pump = db.query(Pump).filter(Pump.pump_id == "SP01-SN-2026-0042").first()
        if not pump:
            pump = Pump(pump_id="SP01-SN-2026-0042", model_name="Pulse SP-01", firmware_version="v1.0.4", status="ONLINE")
            db.add(pump)
            db.commit()

        # 3. Patient & Admission
        patient = db.query(Patient).filter(Patient.patient_id == "P-90214").first()
        if not patient:
            patient = Patient(patient_id="P-90214", first_name="Johnathan", last_name="Doe")
            db.add(patient)
            db.commit()

        admission = db.query(Admission).filter(Admission.patient_id == "P-90214", Admission.status == "ADMITTED").first()
        if not admission:
            admission = Admission(
                admission_id=uuid.uuid4(),
                patient_id="P-90214",
                bed_id="ICU-B01",
                primary_diagnosis="Septic Shock / Acute Respiratory Distress",
                status="ADMITTED"
            )
            db.add(admission)
            db.commit()

        # 4. Device-Patient-Bed Association
        assoc = db.query(DeviceAssociation).filter(DeviceAssociation.pump_id == "SP01-SN-2026-0042", DeviceAssociation.unpaired_at.is_(None)).first()
        if not assoc:
            assoc = DeviceAssociation(
                admission_id=admission.admission_id,
                bed_id="ICU-B01",
                pump_id="SP01-SN-2026-0042",
                paired_by_user_id="NURSE-402"
            )
            db.add(assoc)
            db.commit()

        print("[✓] Seed completed successfully: Bed ICU-B01 linked to Patient P-90214 and Pump SP01-SN-2026-0042.")
    finally:
        db.close()

if __name__ == "__main__":
    seed_database()