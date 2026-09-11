'use client';

import React, { useEffect, useState, useRef } from 'react';
import { QRCodeSVG } from 'qrcode.react';
import { 
  ShieldCheck, Volume2, VolumeX, QrCode, 
  AlertTriangle, CheckCircle2, X, History, Camera, LogOut, 
  Sparkles, UserPlus, FolderClock, Upload, FlaskConical, FileText, 
  Printer, Building2, User, Activity, Droplets, Plus, Unlink, HeartPulse
} from 'lucide-react';
import { Html5Qrcode } from 'html5-qrcode';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'https://pulse-sp01-backend.onrender.com';
const WS_BASE = process.env.NEXT_PUBLIC_WS_URL || 'wss://pulse-sp01-backend.onrender.com/ws/telemetry';

type DeviceType = 'PATIENT_MONITOR' | 'SYRINGE_PUMP' | 'DIALYSIS';

interface AttachedDevice {
  association_id: string;
  device_id: string;
  device_type: DeviceType;
  model_name?: string;
  paired_at: string;
}

interface ActiveBed {
  bed_id: string;
  bed_number: string;
  admission_id?: string;
  patient_mrn?: string;
  patient_name?: string;
  age?: number;
  gender?: string;
  blood_group?: string;
  admission_type?: string;
  attending_doctor?: string;
  admitted_at?: string;
  devices: AttachedDevice[];
}

interface DischargedRecord {
  association_id: string;
  patient_id: string;
  patient_name: string;
  bed_number: string;
  device_id?: string;
  device_type?: string;
  paired_at: string;
  discharged_at: string;
  discharge_type?: string;
  total_volume_ml?: number;
  avg_pressure_kpa?: number;
}

interface DeviceTelemetryPayload {
  device_id: string;
  device_type: DeviceType;
  timestamp: string;
  active_alarms?: string[];
  // Patient Monitor (PM)
  vitals?: {
    heart_rate_bpm: number;
    spo2_pct: number;
    nibp_systolic: number;
    nibp_diastolic: number;
    resp_rate_bpm: number;
    temp_c: number;
  };
  // Syringe Pump (SP)
  infusion_status?: {
    rate_ml_hr: number;
    vtbi_ml: number;
    volume_infused_ml: number;
    time_remaining_sec: number;
    pressure_kpa: number;
  };
  ders?: {
    drug_name: string;
  };
  // Dialysis / CRRT (DL)
  dialysis_metrics?: {
    blood_flow_ml_min: number;
    uf_rate_ml_hr: number;
    total_uf_removed_ml: number;
    venous_pressure_mmhg: number;
    dialysate_temp_c: number;
  };
}

export default function SmartWardCentral() {
  const [beds, setBeds] = useState<ActiveBed[]>([]);
  const [telemetry, setTelemetry] = useState<Record<string, DeviceTelemetryPayload>>({});
  const [connected, setConnected] = useState(false);
  const [audioEnabled, setAudioEnabled] = useState(false);

  // Modals
  const [showAdmissionModal, setShowAdmissionModal] = useState(false);
  const [showAttachDeviceModal, setShowAttachDeviceModal] = useState(false);
  const [targetBedForDevice, setTargetBedForDevice] = useState<ActiveBed | null>(null);
  const [showDischargedModal, setShowDischargedModal] = useState(false);
  const [dischargedRecords, setDischargedRecords] = useState<DischargedRecord[]>([]);
  const [showLabModal, setShowLabModal] = useState(false);
  const [showDossierModal, setShowDossierModal] = useState(false);
  const [selectedPatientDossier, setSelectedPatientDossier] = useState<any>(null);
  const [qrTokenModal, setQrTokenModal] = useState<{ title: string; value: string } | null>(null);

  // Admission Form (Zero Device Coupling)
  const [formBed, setFormBed] = useState('ICU-B1');
  const [formMrn, setFormMrn] = useState('PTN-000001');
  const [formName, setFormName] = useState('RAGHU');
  const [formAge, setFormAge] = useState<number>(45);
  const [formGender, setFormGender] = useState('Male');
  const [formBloodGroup, setFormBloodGroup] = useState('O+');
  const [formPhone, setFormPhone] = useState('+91 98765 43210');
  const [formAddress, setFormAddress] = useState('Flat 402, Green Meadows, Vizag');
  const [formAdmissionType, setFormAdmissionType] = useState('Emergency');
  const [formDoctor, setFormDoctor] = useState('Dr. Robert Vance');
  const [formDiagnosis, setFormDiagnosis] = useState('Acute Hemodynamic Monitoring');

  // Attach Device Modal Form & State
  const [attachTab, setAttachTab] = useState<'AUTO' | 'CAMERA'>('AUTO');
  const [selectedDeviceType, setSelectedDeviceType] = useState<DeviceType>('SYRINGE_PUMP');
  const [deviceSerialId, setDeviceSerialId] = useState('SP01-2026-0001');
  const [deviceCameraActive, setDeviceCameraActive] = useState(false);
  const [deviceScanStatus, setDeviceScanStatus] = useState('Position Hardware QR sticker in camera...');
  const deviceQrScannerRef = useRef<Html5Qrcode | null>(null);

  // Lab Report Modal States
  const [labMrn, setLabMrn] = useState('');
  const [labDept, setLabDept] = useState('PATHOLOGY');
  const [labTestName, setLabTestName] = useState('Complete Blood Count (CBC)');
  const [labHb, setLabHb] = useState('13.2');
  const [labWbc, setLabWbc] = useState('7800');
  const [labPlatelets, setLabPlatelets] = useState('220000');
  const [labNotes, setLabNotes] = useState('');
  const [labLoading, setLabLoading] = useState(false);
  const [labCameraActive, setLabCameraActive] = useState(false);
  const [labScanStatus, setLabScanStatus] = useState('Position patient QR in camera...');
  const labQrScannerRef = useRef<Html5Qrcode | null>(null);

  const audioCtxRef = useRef<AudioContext | null>(null);

  // Fetch Ward Registry & Bed Hierarchy
  const fetchRegistry = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/v1/registry-status`);
      if (res.ok) {
        const data = await res.json();
        setBeds(data.active_associations || data.beds || []);
        if (data.next_suggestions) {
          setFormBed(data.next_suggestions.bed || 'ICU-B1');
          setFormMrn(data.next_suggestions.mrn || 'PTN-000001');
        }
      }
    } catch (e) {
      console.error('Failed to fetch registry', e);
    }
  };

  const fetchDischargedRecords = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/v1/discharged-records`);
      if (res.ok) {
        const data = await res.json();
        setDischargedRecords(data);
        setShowDischargedModal(true);
      }
    } catch (e) {
      alert('Failed to load historical discharge records.');
    }
  };

  useEffect(() => {
    fetchRegistry();
  }, []);

  // Update default serial ID suggestion when device type changes in Auto-Tab
  useEffect(() => {
    const randomSuffix = Math.floor(1000 + Math.random() * 9000);
    if (selectedDeviceType === 'PATIENT_MONITOR') {
      setDeviceSerialId(`PM-2026-${randomSuffix}`);
    } else if (selectedDeviceType === 'SYRINGE_PUMP') {
      setDeviceSerialId(`SP01-2026-${randomSuffix}`);
    } else if (selectedDeviceType === 'DIALYSIS') {
      setDeviceSerialId(`DL-2026-${randomSuffix}`);
    }
  }, [selectedDeviceType]);

  // Audio Alarm Engine
  const playAlarmTone = () => {
    if (!audioEnabled) return;
    try {
      const ctx = audioCtxRef.current || new (window.AudioContext || (window as any).webkitAudioContext)();
      audioCtxRef.current = ctx;
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = 'triangle';
      osc.frequency.setValueAtTime(960, ctx.currentTime);
      gain.gain.setValueAtTime(0.3, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.25);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start();
      osc.stop(ctx.currentTime + 0.25);
    } catch (e) {}
  };

  // WebSocket Ingestion for Multi-Device Telemetry
  useEffect(() => {
    const ws = new WebSocket(WS_BASE);
    ws.onopen = () => setConnected(true);
    ws.onclose = () => setConnected(false);
    ws.onmessage = (event) => {
      try {
        const data: DeviceTelemetryPayload = JSON.parse(event.data);
        setTelemetry((prev) => ({ ...prev, [data.device_id]: data }));
        if (data.active_alarms && data.active_alarms.length > 0) {
          playAlarmTone();
        }
      } catch (err) {}
    };
    return () => ws.close();
  }, [audioEnabled]);

  // 1. Patient Admission (No Device Required)
  const handleAdmitPatient = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const res = await fetch(`${API_BASE}/api/v1/admit-patient`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          bed_number: formBed,
          patient_mrn: formMrn,
          patient_name: formName.trim(),
          age: Number(formAge),
          gender: formGender,
          blood_group: formBloodGroup,
          phone_number: formPhone,
          address: formAddress,
          admission_type: formAdmissionType,
          attending_doctor: formDoctor,
          primary_diagnosis: formDiagnosis
        })
      });
      const data = await res.json();
      if (res.ok && data.status === 'success') {
        setShowAdmissionModal(false);
        await fetchRegistry();
      } else {
        alert(data.detail || data.message || 'Error admitting patient.');
      }
    } catch (err) {
      alert('Network error connecting to backend.');
    }
  };

  // 2. Attach Device Binding (Multi-Device dynamically per bed)
  const handleAttachDeviceSubmit = async (deviceIdToBind?: string, deviceTypeToBind?: DeviceType) => {
    if (!targetBedForDevice) return;
    const finalDeviceId = (deviceIdToBind || deviceSerialId).trim();
    const finalDeviceType = deviceTypeToBind || selectedDeviceType;

    try {
      const res = await fetch(`${API_BASE}/api/v1/devices/attach`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          bed_number: targetBedForDevice.bed_number,
          patient_mrn: targetBedForDevice.patient_mrn,
          admission_id: targetBedForDevice.admission_id,
          device_id: finalDeviceId,
          device_type: finalDeviceType
        })
      });
      const data = await res.json();
      if (res.ok && data.status === 'success') {
        if (deviceQrScannerRef.current?.isScanning) {
          await deviceQrScannerRef.current.stop();
        }
        setDeviceCameraActive(false);
        setShowAttachDeviceModal(false);
        await fetchRegistry();
      } else {
        alert(data.detail || data.message || 'Failed to attach device.');
      }
    } catch (err: any) {
      alert(`Error attaching device: ${err.message}`);
    }
  };

  // 3. Unbind an Individual Device from a Bed
  const handleUnbindDevice = async (deviceId: string, bedNumber: string) => {
    if (!confirm(`Unbind and release equipment ${deviceId} from Bed ${bedNumber}? Patient will remain admitted.`)) return;
    try {
      const res = await fetch(`${API_BASE}/api/v1/devices/unbind`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ device_id: deviceId })
      });
      if (res.ok) {
        await fetchRegistry();
      } else {
        alert('Failed to release device.');
      }
    } catch (err) {
      alert('Network error releasing device.');
    }
  };

  // 4. Discharge Patient (Releases Bed and All Attached Hardware)
  const handleDischargePatient = async (bed: ActiveBed) => {
    const dischargeReason = prompt(
      `Discharge patient ${bed.patient_name} (${bed.patient_mrn})?\nEnter discharge type:\n1. Routine / Recovered\n2. Referred / Transferred\n3. Discharged on Request (DOR)\n4. LAMA`, 
      "Routine / Recovered"
    );
    if (!dischargeReason) return;

    try {
      await fetch(`${API_BASE}/api/v1/discharge-encounter`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ 
          bed_number: bed.bed_number, 
          patient_mrn: bed.patient_mrn,
          discharge_type: dischargeReason 
        })
      });
      await fetchRegistry();
    } catch (err) {
      alert('Error discharging patient.');
    }
  };

  // 5. Camera QR Decoder for Device Stickers (e.g. "PUMP:SP01-...", "MONITOR:PM-...", "DIALYSIS:DL-...")
  const decodeDeviceQrText = (decodedText: string) => {
    let devId = decodedText.trim();
    let devType: DeviceType = 'SYRINGE_PUMP';

    if (decodedText.startsWith('MONITOR:') || decodedText.includes('TYPE:PM')) {
      devType = 'PATIENT_MONITOR';
      devId = decodedText.replace('MONITOR:', '').split('|')[0];
    } else if (decodedText.startsWith('DIALYSIS:') || decodedText.includes('TYPE:DL')) {
      devType = 'DIALYSIS';
      devId = decodedText.replace('DIALYSIS:', '').split('|')[0];
    } else if (decodedText.startsWith('PUMP:') || decodedText.includes('TYPE:SP')) {
      devType = 'SYRINGE_PUMP';
      devId = decodedText.replace('PUMP:', '').split('|')[0];
    } else if (devId.startsWith('PM-')) {
      devType = 'PATIENT_MONITOR';
    } else if (devId.startsWith('DL-')) {
      devType = 'DIALYSIS';
    }

    setDeviceSerialId(devId);
    setSelectedDeviceType(devType);
    handleAttachDeviceSubmit(devId, devType);
  };

  // Device Camera Lifecycle
  useEffect(() => {
    if (!deviceCameraActive) return;
    setDeviceScanStatus('Requesting camera for hardware pairing...');
    const elementId = 'device-qr-reader';

    const timer = setTimeout(async () => {
      try {
        const scanner = new Html5Qrcode(elementId);
        deviceQrScannerRef.current = scanner;
        await scanner.start(
          { facingMode: 'environment' },
          { fps: 15, qrbox: { width: 220, height: 220 } },
          async (decodedText) => {
            decodeDeviceQrText(decodedText);
          },
          () => {}
        );
        setDeviceScanStatus('Camera Active: Point at device chassis QR barcode');
      } catch (err) {
        setDeviceScanStatus('Camera unavailable or permission denied.');
      }
    }, 200);

    return () => {
      clearTimeout(timer);
      if (deviceQrScannerRef.current && deviceQrScannerRef.current.isScanning) {
        deviceQrScannerRef.current.stop().catch(() => {});
      }
    };
  }, [deviceCameraActive]);

  // Lab Report Camera Scanner Lifecycle
  useEffect(() => {
    if (!labCameraActive) return;
    setLabScanStatus('Starting patient wristband scanner...');
    const elementId = 'lab-qr-reader';

    const timer = setTimeout(async () => {
      try {
        const scanner = new Html5Qrcode(elementId);
        labQrScannerRef.current = scanner;
        await scanner.start(
          { facingMode: 'environment' },
          { fps: 15, qrbox: { width: 220, height: 220 } },
          async (decodedText) => {
            let foundMrn = decodedText.trim();
            if (decodedText.includes('|')) {
              decodedText.split('|').forEach(p => {
                const [k, v] = p.split(':');
                if (k === 'MRN') foundMrn = v;
              });
            } else if (decodedText.startsWith('MRN:')) {
              foundMrn = decodedText.replace('MRN:', '');
            }
            setLabMrn(foundMrn);
            if (labQrScannerRef.current?.isScanning) await labQrScannerRef.current.stop();
            setLabCameraActive(false);
          },
          () => {}
        );
        setLabScanStatus('Scanning... Point at patient wristband');
      } catch (err) {
        setLabScanStatus('Camera access error.');
      }
    }, 200);

    return () => {
      clearTimeout(timer);
      if (labQrScannerRef.current && labQrScannerRef.current.isScanning) {
        labQrScannerRef.current.stop().catch(() => {});
      }
    };
  }, [labCameraActive]);

  // Attach Diagnostic Lab Report
  const handleAttachReport = async (e: React.FormEvent) => {
    e.preventDefault();
    setLabLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/v1/reports/attach`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          patient_mrn: labMrn.trim(),
          department: labDept,
          test_name: labTestName,
          parameters: labDept === 'PATHOLOGY' 
            ? { 'Hemoglobin (g/dL)': labHb, 'WBC (/mcL)': labWbc, 'Platelets (/mcL)': labPlatelets }
            : { 'Modality': labTestName, 'Findings': labNotes },
          technician_notes: labNotes,
          technician_name: 'Central Diagnostic Wing'
        })
      });
      const data = await res.json();
      if (res.ok && data.status === 'success') {
        alert('Diagnostic investigation attached successfully.');
        setShowLabModal(false);
        setLabNotes('');
      } else {
        alert(data.detail || data.message || 'Failed to attach investigation.');
      }
    } catch (err: any) {
      alert(`Network error: ${err.message}`);
    } finally {
      setLabLoading(false);
    }
  };

  // Open Full Patient Dossier
  const openDossier = async (mrn: string) => {
    try {
      const res = await fetch(`${API_BASE}/api/v1/patient-dossier/${mrn}`);
      if (res.ok) {
        const data = await res.json();
        setSelectedPatientDossier(data);
        setShowDossierModal(true);
      } else {
        alert('Could not retrieve patient dossier.');
      }
    } catch (err) {
      alert('Error fetching patient clinical dossier.');
    }
  };

  return (
    <main className="min-h-screen bg-slate-900 text-slate-100 p-6 font-sans">
      {/* Top Clinical Header */}
      <header className="mb-6 flex flex-col lg:flex-row lg:items-center justify-between gap-4 bg-slate-800/80 backdrop-blur-md p-6 rounded-2xl border border-slate-700 shadow-lg">
        <div>
          <div className="flex items-center space-x-3">
            <h1 className="text-2xl font-black text-white tracking-tight flex items-center gap-2">
              <Activity className="w-7 h-7 text-indigo-400 animate-pulse" />
              Pulse Multi-Device Central Telemetry
            </h1>
            <span className="flex items-center text-xs font-semibold px-2.5 py-1 rounded-full bg-emerald-950 text-emerald-300 border border-emerald-700">
              <ShieldCheck className="w-3.5 h-3.5 mr-1 text-emerald-400" /> Smart ICU Station
            </span>
          </div>
          <p className="text-xs text-slate-400 mt-1">
            Enterprise Fleet: {beds.length} Active Bed Encounters | Real-time Multimodal Device Aggregator
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2.5">
          <button
            onClick={() => {
              setLabMrn(beds[0]?.patient_mrn || '');
              setLabCameraActive(false);
              setShowLabModal(true);
            }}
            className="flex items-center space-x-1.5 px-3.5 py-2 rounded-xl text-xs font-bold bg-emerald-600 text-white hover:bg-emerald-500 transition shadow"
          >
            <FlaskConical className="w-4 h-4" />
            <span>Attach Lab/Scan</span>
          </button>

          <button
            onClick={fetchDischargedRecords}
            className="flex items-center space-x-1.5 px-3.5 py-2 rounded-xl text-xs font-bold bg-amber-600 text-white hover:bg-amber-500 transition shadow"
          >
            <FolderClock className="w-4 h-4" />
            <span>Discharged Records</span>
          </button>

          <button
            onClick={() => setShowAdmissionModal(true)}
            className="flex items-center space-x-1.5 px-3.5 py-2 rounded-xl text-xs font-bold bg-indigo-600 text-white hover:bg-indigo-500 transition shadow"
          >
            <UserPlus className="w-4 h-4" />
            <span>+ Admit New Patient</span>
          </button>

          <button
            onClick={() => setAudioEnabled(!audioEnabled)}
            className={`flex items-center space-x-1.5 px-3.5 py-2 rounded-xl text-xs font-bold border transition ${
              audioEnabled ? 'bg-amber-950/80 text-amber-300 border-amber-600' : 'bg-slate-800 text-slate-400 border-slate-700'
            }`}
          >
            {audioEnabled ? <Volume2 className="w-4 h-4 text-amber-400" /> : <VolumeX className="w-4 h-4 text-slate-500" />}
            <span>{audioEnabled ? 'Alarms: ON' : 'Alarms: MUTED'}</span>
          </button>

          <div className="flex items-center space-x-2 px-3 py-2 bg-slate-950/60 rounded-xl border border-slate-700">
            <span className={`w-2.5 h-2.5 rounded-full ${connected ? 'bg-emerald-400 shadow-[0_0_8px_#34d399]' : 'bg-red-500 animate-ping'}`} />
            <span className="text-xs font-mono font-medium text-slate-300">
              {connected ? 'WS: LIVE' : 'WS: CONNECTING'}
            </span>
          </div>
        </div>
      </header>

      {/* Multi-Device Bed Stations Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-6">
        {beds.map((b) => {
          const hasDevices = b.devices && b.devices.length > 0;

          return (
            <div
              key={b.bed_id || b.bed_number}
              className="bg-slate-800/90 rounded-2xl border border-slate-700/80 shadow-md p-5 flex flex-col justify-between transition-all hover:border-slate-600"
            >
              <div>
                {/* Bed Card Header */}
                <div className="flex items-center justify-between pb-3 border-b border-slate-700/60">
                  <div className="flex items-center space-x-2">
                    <span className="text-xl font-black text-white tracking-wide">{b.bed_number}</span>
                    <span className="px-2 py-0.5 text-xs font-mono font-semibold bg-indigo-950 text-indigo-300 rounded border border-indigo-700">
                      {b.patient_mrn || 'AVAILABLE'}
                    </span>
                  </div>
                  <div className="flex items-center space-x-1.5">
                    {b.patient_mrn && (
                      <button
                        onClick={() => openDossier(b.patient_mrn!)}
                        title="View Full Dossier"
                        className="p-1.5 text-slate-400 hover:text-indigo-300 rounded-lg hover:bg-slate-700 transition"
                      >
                        <FileText className="w-4 h-4" />
                      </button>
                    )}
                    <button
                      onClick={() => setQrTokenModal({ title: `Bed Station QR`, value: `BED:${b.bed_number}|MRN:${b.patient_mrn || 'NONE'}` })}
                      title="View QR Token"
                      className="p-1.5 text-slate-400 hover:text-slate-200 rounded-lg hover:bg-slate-700 transition"
                    >
                      <QrCode className="w-4 h-4" />
                    </button>
                  </div>
                </div>

                {/* Patient Information Strip */}
                <div className="mt-3 flex justify-between items-start">
                  <div>
                    <h2 className="text-sm font-bold text-white tracking-tight">
                      {b.patient_name || 'Bed Station Vacant'}
                    </h2>
                    {b.patient_mrn && (
                      <div className="text-[11px] text-slate-400 mt-0.5">
                        <span>{b.age || 45} Y / {b.gender || 'M'}</span> • <span className="font-semibold text-rose-400">{b.blood_group || 'O+'}</span>
                        <span className="block text-[10px] text-slate-400 mt-0.5 font-sans">Doc: {b.attending_doctor || 'Staff On-Duty'}</span>
                      </div>
                    )}
                  </div>

                  {b.patient_mrn && (
                    <button
                      onClick={() => {
                        setTargetBedForDevice(b);
                        setAttachTab('AUTO');
                        setDeviceCameraActive(false);
                        setShowAttachDeviceModal(true);
                      }}
                      className="text-xs font-bold text-indigo-300 bg-indigo-950/80 hover:bg-indigo-900 border border-indigo-700 px-2.5 py-1 rounded-xl transition flex items-center gap-1 shadow-sm"
                    >
                      <Plus className="w-3.5 h-3.5" /> Attach Device
                    </button>
                  )}
                </div>

                {/* Attached Dynamic Device Bays */}
                <div className="mt-4 space-y-3">
                  {!hasDevices ? (
                    <div className="p-4 rounded-xl border border-dashed border-slate-700 text-center bg-slate-900/40 text-slate-400 text-xs">
                      No telemetry equipment paired. Click <strong className="text-indigo-400">"+ Attach Device"</strong> to bind a Patient Monitor, Syringe Pump, or Dialysis unit.
                    </div>
                  ) : (
                    b.devices.map((dev) => {
                      const live = telemetry[dev.device_id];
                      const hasAlarm = live?.active_alarms && live.active_alarms.length > 0;

                      // 🫀 Patient Monitor Bay
                      if (dev.device_type === 'PATIENT_MONITOR') {
                        const hr = live?.vitals?.heart_rate_bpm ?? 76;
                        const spo2 = live?.vitals?.spo2_pct ?? 99;
                        const sys = live?.vitals?.nibp_systolic ?? 120;
                        const dia = live?.vitals?.nibp_diastolic ?? 80;
                        const resp = live?.vitals?.resp_rate_bpm ?? 16;
                        const temp = live?.vitals?.temp_c ?? 36.8;

                        return (
                          <div key={dev.device_id} className={`p-3 rounded-xl border transition ${hasAlarm ? 'bg-red-950/40 border-red-500' : 'bg-slate-900/80 border-emerald-900/60'}`}>
                            <div className="flex justify-between items-center pb-2 border-b border-slate-800">
                              <div className="flex items-center gap-1.5 text-xs font-bold text-emerald-400">
                                <HeartPulse className="w-3.5 h-3.5 animate-pulse" />
                                <span>Patient Monitor</span>
                                <span className="text-[10px] font-mono text-slate-400">({dev.device_id})</span>
                              </div>
                              <button
                                onClick={() => handleUnbindDevice(dev.device_id, b.bed_number)}
                                title="Unbind Monitor"
                                className="text-slate-500 hover:text-rose-400 transition"
                              >
                                <Unlink className="w-3.5 h-3.5" />
                              </button>
                            </div>
                            <div className="grid grid-cols-4 gap-2 text-center mt-2.5">
                              <div className="bg-slate-950/60 p-1.5 rounded-lg border border-slate-800">
                                <span className="text-[10px] text-emerald-400 font-bold block">HR (bpm)</span>
                                <span className="text-lg font-black text-white">{hr}</span>
                              </div>
                              <div className="bg-slate-950/60 p-1.5 rounded-lg border border-slate-800">
                                <span className="text-[10px] text-cyan-400 font-bold block">SpO₂ (%)</span>
                                <span className="text-lg font-black text-cyan-300">{spo2}%</span>
                              </div>
                              <div className="bg-slate-950/60 p-1.5 rounded-lg border border-slate-800">
                                <span className="text-[10px] text-amber-400 font-bold block">NIBP</span>
                                <span className="text-xs font-black text-amber-200 mt-1 block">{sys}/{dia}</span>
                              </div>
                              <div className="bg-slate-950/60 p-1.5 rounded-lg border border-slate-800">
                                <span className="text-[10px] text-purple-400 font-bold block">Resp/T°</span>
                                <span className="text-xs font-black text-slate-300 mt-1 block">{resp} | {temp}°</span>
                              </div>
                            </div>
                          </div>
                        );
                      }

                      // 💉 Syringe Pump Bay
                      if (dev.device_type === 'SYRINGE_PUMP') {
                        const drug = live?.ders?.drug_name || 'Norepinephrine';
                        const rate = live?.infusion_status?.rate_ml_hr ?? 5.0;
                        const delivered = live?.infusion_status?.volume_infused_ml ?? 8.5;
                        const vtbi = live?.infusion_status?.vtbi_ml ?? 50.0;
                        const pressure = live?.infusion_status?.pressure_kpa ?? 39.5;
                        const pct = Math.min(100, Math.round((delivered / (vtbi || 50)) * 100));

                        return (
                          <div key={dev.device_id} className={`p-3 rounded-xl border transition ${hasAlarm ? 'bg-red-950/40 border-red-500' : 'bg-slate-900/80 border-indigo-900/60'}`}>
                            <div className="flex justify-between items-center pb-2 border-b border-slate-800">
                              <div className="flex items-center gap-1.5 text-xs font-bold text-indigo-400">
                                <Activity className="w-3.5 h-3.5" />
                                <span>Syringe Pump ({drug})</span>
                                <span className="text-[10px] font-mono text-slate-400">({dev.device_id})</span>
                              </div>
                              <button
                                onClick={() => handleUnbindDevice(dev.device_id, b.bed_number)}
                                title="Unbind Pump"
                                className="text-slate-500 hover:text-rose-400 transition"
                              >
                                <Unlink className="w-3.5 h-3.5" />
                              </button>
                            </div>
                            <div className="flex justify-between items-center mt-2">
                              <div>
                                <span className="text-[10px] text-slate-400 block font-mono">Line Pressure: {pressure} kPa</span>
                                <span className="text-[11px] text-slate-300 font-mono">{delivered.toFixed(1)} / {vtbi} mL ({pct}%)</span>
                              </div>
                              <div className="text-right">
                                <span className="text-xl font-black text-indigo-300">{rate.toFixed(1)}</span>
                                <span className="text-[10px] text-slate-400 ml-1 font-semibold">mL/h</span>
                              </div>
                            </div>
                            <div className="h-1.5 w-full bg-slate-800 rounded-full overflow-hidden mt-2">
                              <div className="h-full bg-indigo-500 transition-all duration-300" style={{ width: `${pct}%` }} />
                            </div>
                          </div>
                        );
                      }

                      // 🩸 Dialysis / CRRT Bay
                      if (dev.device_type === 'DIALYSIS') {
                        const bfr = live?.dialysis_metrics?.blood_flow_ml_min ?? 250;
                        const ufr = live?.dialysis_metrics?.uf_rate_ml_hr ?? 300;
                        const totalUf = live?.dialysis_metrics?.total_uf_removed_ml ?? 1200;
                        const venousPres = live?.dialysis_metrics?.venous_pressure_mmhg ?? 110;

                        return (
                          <div key={dev.device_id} className={`p-3 rounded-xl border transition ${hasAlarm ? 'bg-red-950/40 border-red-500' : 'bg-slate-900/80 border-rose-900/60'}`}>
                            <div className="flex justify-between items-center pb-2 border-b border-slate-800">
                              <div className="flex items-center gap-1.5 text-xs font-bold text-rose-400">
                                <Droplets className="w-3.5 h-3.5 animate-bounce" />
                                <span>Hemodialysis / CRRT</span>
                                <span className="text-[10px] font-mono text-slate-400">({dev.device_id})</span>
                              </div>
                              <button
                                onClick={() => handleUnbindDevice(dev.device_id, b.bed_number)}
                                title="Unbind Dialysis"
                                className="text-slate-500 hover:text-rose-400 transition"
                              >
                                <Unlink className="w-3.5 h-3.5" />
                              </button>
                            </div>
                            <div className="grid grid-cols-3 gap-2 text-center mt-2.5">
                              <div className="bg-slate-950/60 p-1.5 rounded-lg border border-slate-800">
                                <span className="text-[9px] text-slate-400 block uppercase">Blood Flow</span>
                                <span className="text-xs font-black text-rose-300">{bfr} mL/m</span>
                              </div>
                              <div className="bg-slate-950/60 p-1.5 rounded-lg border border-slate-800">
                                <span className="text-[9px] text-slate-400 block uppercase">UF Rate</span>
                                <span className="text-xs font-black text-amber-300">{ufr} mL/h</span>
                              </div>
                              <div className="bg-slate-950/60 p-1.5 rounded-lg border border-slate-800">
                                <span className="text-[9px] text-slate-400 block uppercase">Total Removed</span>
                                <span className="text-xs font-black text-emerald-400">{totalUf} mL</span>
                              </div>
                            </div>
                          </div>
                        );
                      }

                      return null;
                    })
                  )}
                </div>
              </div>

              {/* Bed Card Footer */}
              <div className="mt-5 pt-3 border-t border-slate-700/60 flex items-center justify-between">
                <span className="text-[11px] text-slate-400 font-mono">
                  {b.admitted_at ? `Admitted: ${new Date(b.admitted_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}` : 'Bed Ready'}
                </span>
                {b.patient_mrn && (
                  <button
                    onClick={() => handleDischargePatient(b)}
                    className="flex items-center space-x-1 text-xs font-semibold text-rose-400 hover:text-rose-300 bg-rose-950/60 hover:bg-rose-900/80 px-2.5 py-1 rounded-lg border border-rose-800 transition"
                  >
                    <LogOut className="w-3.5 h-3.5" />
                    <span>Discharge Patient</span>
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* MODAL: Admit Patient (Zero Hardware Coupling) */}
      {showAdmissionModal && (
        <div className="fixed inset-0 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4 z-50">
          <div className="bg-slate-800 rounded-2xl max-w-xl w-full p-6 shadow-2xl border border-slate-700 max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between pb-4 border-b border-slate-700">
              <div>
                <h3 className="text-lg font-bold text-white">Patient Clinical Admission</h3>
                <p className="text-xs text-slate-400">Admit patient to an ICU Bed Station. (Equipment attached separately).</p>
              </div>
              <button onClick={() => setShowAdmissionModal(false)} className="text-slate-400 hover:text-white"><X className="w-5 h-5" /></button>
            </div>

            <form onSubmit={handleAdmitPatient} className="mt-4 space-y-4">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-bold text-slate-300 mb-1">ICU Bed Station</label>
                  <input value={formBed} onChange={(e) => setFormBed(e.target.value)} required className="w-full px-3 py-2 rounded-xl bg-slate-900 border border-slate-700 text-sm text-white focus:outline-none focus:border-indigo-500" />
                </div>
                <div>
                  <label className="block text-xs font-bold text-slate-300 mb-1">Patient MRN (Auto-ID)</label>
                  <input value={formMrn} onChange={(e) => setFormMrn(e.target.value)} required className="w-full px-3 py-2 rounded-xl bg-slate-900 border border-slate-700 text-sm font-mono text-indigo-300 focus:outline-none" />
                </div>
              </div>

              <div>
                <label className="block text-xs font-bold text-slate-300 mb-1">Patient Full Name</label>
                <input value={formName} onChange={(e) => setFormName(e.target.value)} required placeholder="e.g. RAGHU" className="w-full px-3 py-2 rounded-xl bg-slate-900 border border-slate-700 text-sm text-white focus:outline-none focus:border-indigo-500" />
              </div>

              <div className="grid grid-cols-3 gap-3">
                <div>
                  <label className="block text-xs font-bold text-slate-300 mb-1">Age (Years)</label>
                  <input type="number" value={formAge} onChange={(e) => setFormAge(Number(e.target.value))} required className="w-full px-3 py-2 rounded-xl bg-slate-900 border border-slate-700 text-sm text-white focus:outline-none" />
                </div>
                <div>
                  <label className="block text-xs font-bold text-slate-300 mb-1">Gender</label>
                  <select value={formGender} onChange={(e) => setFormGender(e.target.value)} className="w-full px-3 py-2 rounded-xl bg-slate-900 border border-slate-700 text-sm text-white focus:outline-none">
                    <option value="Male">Male</option>
                    <option value="Female">Female</option>
                    <option value="Other">Other</option>
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-bold text-slate-300 mb-1">Blood Group</label>
                  <select value={formBloodGroup} onChange={(e) => setFormBloodGroup(e.target.value)} className="w-full px-3 py-2 rounded-xl bg-slate-900 border border-slate-700 text-sm font-bold text-rose-400 focus:outline-none">
                    <option value="A+">A+</option>
                    <option value="A-">A-</option>
                    <option value="B+">B+</option>
                    <option value="B-">B-</option>
                    <option value="AB+">AB+</option>
                    <option value="AB-">AB-</option>
                    <option value="O+">O+</option>
                    <option value="O-">O-</option>
                  </select>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-bold text-slate-300 mb-1">Admission Type</label>
                  <select value={formAdmissionType} onChange={(e) => setFormAdmissionType(e.target.value)} className="w-full px-3 py-2 rounded-xl bg-slate-900 border border-slate-700 text-sm text-white focus:outline-none">
                    <option value="Emergency">Emergency</option>
                    <option value="Elective / Planned">Elective / Planned</option>
                    <option value="ICU Transfer">ICU Transfer</option>
                    <option value="Trauma / Critical">Trauma / Critical</option>
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-bold text-slate-300 mb-1">Attending Doctor</label>
                  <input value={formDoctor} onChange={(e) => setFormDoctor(e.target.value)} required className="w-full px-3 py-2 rounded-xl bg-slate-900 border border-slate-700 text-sm text-white focus:outline-none" />
                </div>
              </div>

              <div>
                <label className="block text-xs font-bold text-slate-300 mb-1">Contact Phone Number</label>
                <input value={formPhone} onChange={(e) => setFormPhone(e.target.value)} className="w-full px-3 py-2 rounded-xl bg-slate-900 border border-slate-700 text-sm text-white focus:outline-none" />
              </div>

              <div>
                <label className="block text-xs font-bold text-slate-300 mb-1">Residential Address</label>
                <input value={formAddress} onChange={(e) => setFormAddress(e.target.value)} className="w-full px-3 py-2 rounded-xl bg-slate-900 border border-slate-700 text-sm text-white focus:outline-none" />
              </div>

              <button type="submit" className="w-full py-2.5 bg-indigo-600 hover:bg-indigo-500 text-white rounded-xl text-sm font-bold transition shadow">
                Complete Inpatient Admission
              </button>
            </form>
          </div>
        </div>
      )}

      {/* MODAL: Attach Device to Patient Bed (Live Camera QR Scanner or Auto-Select) */}
      {showAttachDeviceModal && targetBedForDevice && (
        <div className="fixed inset-0 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4 z-50">
          <div className="bg-slate-800 rounded-2xl max-w-md w-full p-6 shadow-2xl border border-slate-700">
            <div className="flex items-center justify-between pb-3 border-b border-slate-700">
              <div>
                <h3 className="text-base font-bold text-white">Attach Telemetry Device</h3>
                <p className="text-xs text-slate-400">Target: {targetBedForDevice.bed_number} ({targetBedForDevice.patient_name})</p>
              </div>
              <button 
                onClick={async () => {
                  if (deviceQrScannerRef.current?.isScanning) await deviceQrScannerRef.current.stop();
                  setDeviceCameraActive(false);
                  setShowAttachDeviceModal(false);
                }} 
                className="text-slate-400 hover:text-white"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Toggle Tabs */}
            <div className="grid grid-cols-2 gap-2 mt-4 bg-slate-900 p-1 rounded-xl border border-slate-700">
              <button
                type="button"
                onClick={async () => {
                  if (deviceQrScannerRef.current?.isScanning) await deviceQrScannerRef.current.stop();
                  setDeviceCameraActive(false);
                  setAttachTab('AUTO');
                }}
                className={`py-1.5 text-xs font-bold rounded-lg transition ${attachTab === 'AUTO' ? 'bg-indigo-600 text-white shadow' : 'text-slate-400 hover:text-white'}`}
              >
                Auto-Select & QR Code
              </button>
              <button
                type="button"
                onClick={() => {
                  setAttachTab('CAMERA');
                  setDeviceCameraActive(true);
                }}
                className={`py-1.5 text-xs font-bold rounded-lg transition ${attachTab === 'CAMERA' ? 'bg-indigo-600 text-white shadow' : 'text-slate-400 hover:text-white'}`}
              >
                📷 Live Camera Scanner
              </button>
            </div>

            {attachTab === 'AUTO' ? (
              <div className="mt-4 space-y-4">
                <div>
                  <label className="block text-xs font-bold text-slate-300 mb-1">Select Device Category</label>
                  <select
                    value={selectedDeviceType}
                    onChange={(e) => setSelectedDeviceType(e.target.value as DeviceType)}
                    className="w-full px-3 py-2 rounded-xl bg-slate-900 border border-slate-700 text-sm text-white focus:outline-none"
                  >
                    <option value="SYRINGE_PUMP">💉 Syringe Infusion Pump (SP)</option>
                    <option value="PATIENT_MONITOR">🫀 Multi-Para Patient Monitor (PM)</option>
                    <option value="DIALYSIS">🩸 Hemodialysis / CRRT Unit (DL)</option>
                  </select>
                </div>

                <div>
                  <label className="block text-xs font-bold text-slate-300 mb-1">Hardware Serial Number</label>
                  <input
                    value={deviceSerialId}
                    onChange={(e) => setDeviceSerialId(e.target.value)}
                    required
                    className="w-full px-3 py-2 rounded-xl bg-slate-900 border border-slate-700 text-sm font-mono text-indigo-300 focus:outline-none"
                  />
                </div>

                {/* Auto-Generated Hardware QR Preview */}
                <div className="p-4 bg-slate-900 rounded-xl border border-slate-700 flex flex-col items-center justify-center">
                  <span className="text-[11px] text-slate-400 font-semibold mb-2">Hardware Chassis Pairing Token</span>
                  <div className="p-2 bg-white rounded-lg">
                    <QRCodeSVG value={`${selectedDeviceType}:${deviceSerialId}`} size={130} level="H" />
                  </div>
                  <span className="text-[10px] font-mono text-slate-400 mt-2">{selectedDeviceType}:{deviceSerialId}</span>
                </div>

                <button
                  type="button"
                  onClick={() => handleAttachDeviceSubmit()}
                  className="w-full py-2.5 bg-indigo-600 hover:bg-indigo-500 text-white rounded-xl text-sm font-bold transition shadow"
                >
                  Confirm & Attach to Bed Station
                </button>
              </div>
            ) : (
              <div className="mt-4 space-y-3">
                <p className="text-xs text-slate-400 text-center">{deviceScanStatus}</p>
                <div className="rounded-xl overflow-hidden border border-slate-700 bg-black min-h-[220px] flex items-center justify-center">
                  <div id="device-qr-reader" className="w-full h-full" />
                </div>
                <p className="text-[11px] text-slate-400 text-center">Point camera at sticker: <code>PUMP:...</code>, <code>MONITOR:...</code>, or <code>DIALYSIS:...</code></p>
              </div>
            )}
          </div>
        </div>
      )}

      {/* MODAL: Attach Diagnostic Reports with Wristband Scanner */}
      {showLabModal && (
        <div className="fixed inset-0 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4 z-50">
          <div className="bg-slate-800 rounded-2xl max-w-lg w-full p-6 shadow-2xl border border-slate-700 max-h-[92vh] overflow-y-auto">
            <div className="flex items-center justify-between pb-3 border-b border-slate-700">
              <div className="flex items-center space-x-2">
                <FlaskConical className="w-5 h-5 text-emerald-400" />
                <h3 className="text-base font-bold text-white">Attach Diagnostic / Lab Report</h3>
              </div>
              <button 
                onClick={async () => {
                  if (labQrScannerRef.current?.isScanning) await labQrScannerRef.current.stop();
                  setLabCameraActive(false);
                  setShowLabModal(false);
                }} 
                className="text-slate-400 hover:text-white"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Embedded Live Camera Scanner View */}
            {labCameraActive && (
              <div className="mt-3 p-3 bg-slate-950 rounded-xl border border-slate-700 text-center space-y-2">
                <div className="flex items-center justify-between text-xs text-emerald-400 font-semibold px-1">
                  <span className="flex items-center gap-1"><Camera className="w-3.5 h-3.5 animate-pulse" /> {labScanStatus}</span>
                  <button
                    type="button"
                    onClick={async () => {
                      if (labQrScannerRef.current?.isScanning) await labQrScannerRef.current.stop();
                      setLabCameraActive(false);
                    }}
                    className="text-slate-400 hover:text-white text-xs bg-slate-800 px-2 py-0.5 rounded"
                  >
                    Close
                  </button>
                </div>
                <div className="rounded-lg overflow-hidden min-h-[200px] flex items-center justify-center bg-black">
                  <div id="lab-qr-reader" className="w-full h-full" />
                </div>
              </div>
            )}

            <form onSubmit={handleAttachReport} className="mt-4 space-y-4">
              <div>
                <div className="flex justify-between items-center mb-1">
                  <label className="block text-xs font-bold text-slate-300">Target Patient MRN</label>
                  {!labCameraActive && (
                    <button
                      type="button"
                      onClick={() => setLabCameraActive(true)}
                      className="flex items-center space-x-1 text-[11px] font-bold text-emerald-400 bg-emerald-950/80 hover:bg-emerald-900 border border-emerald-700 px-2 py-0.5 rounded-lg transition"
                    >
                      <Camera className="w-3.5 h-3.5 text-emerald-400" />
                      <span>Scan Patient Wristband</span>
                    </button>
                  )}
                </div>
                <input
                  value={labMrn}
                  onChange={(e) => setLabMrn(e.target.value)}
                  placeholder="e.g. PTN-000001"
                  required
                  className="w-full px-3 py-2 rounded-xl bg-slate-900 border border-slate-700 text-sm font-mono text-white focus:outline-none"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-bold text-slate-300 mb-1">Department</label>
                  <select
                    value={labDept}
                    onChange={(e) => {
                      setLabDept(e.target.value);
                      if (e.target.value === 'RADIOLOGY') setLabTestName('Chest X-Ray AP View');
                      else setLabTestName('Complete Blood Count (CBC)');
                    }}
                    className="w-full px-3 py-2 rounded-xl bg-slate-900 border border-slate-700 text-sm text-white focus:outline-none"
                  >
                    <option value="PATHOLOGY">Pathology (Blood/Urine)</option>
                    <option value="RADIOLOGY">Radiology (X-Ray/Scans)</option>
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-bold text-slate-300 mb-1">Investigation Name</label>
                  <input
                    value={labTestName}
                    onChange={(e) => setLabTestName(e.target.value)}
                    required
                    className="w-full px-3 py-2 rounded-xl bg-slate-900 border border-slate-700 text-sm text-white focus:outline-none"
                  />
                </div>
              </div>

              {labDept === 'PATHOLOGY' ? (
                <div className="grid grid-cols-3 gap-2 bg-slate-900 p-3 rounded-xl border border-slate-700">
                  <div>
                    <label className="block text-[11px] font-bold text-slate-400">Hb (g/dL)</label>
                    <input value={labHb} onChange={(e) => setLabHb(e.target.value)} className="w-full px-2 py-1 bg-slate-800 rounded border border-slate-700 text-xs text-white mt-1" />
                  </div>
                  <div>
                    <label className="block text-[11px] font-bold text-slate-400">WBC (/mcL)</label>
                    <input value={labWbc} onChange={(e) => setLabWbc(e.target.value)} className="w-full px-2 py-1 bg-slate-800 rounded border border-slate-700 text-xs text-white mt-1" />
                  </div>
                  <div>
                    <label className="block text-[11px] font-bold text-slate-400">Platelets</label>
                    <input value={labPlatelets} onChange={(e) => setLabPlatelets(e.target.value)} className="w-full px-2 py-1 bg-slate-800 rounded border border-slate-700 text-xs text-white mt-1" />
                  </div>
                </div>
              ) : null}

              <div>
                <label className="block text-xs font-bold text-slate-300 mb-1">Clinical Observation / Notes</label>
                <textarea
                  value={labNotes}
                  onChange={(e) => setLabNotes(e.target.value)}
                  rows={2}
                  placeholder="e.g. Normal blood morphology or Clear lung fields"
                  className="w-full px-3 py-2 rounded-xl bg-slate-900 border border-slate-700 text-sm text-white focus:outline-none"
                />
              </div>

              <button
                type="submit"
                disabled={labLoading}
                className="w-full py-2.5 bg-emerald-600 hover:bg-emerald-500 text-white rounded-xl text-sm font-bold transition shadow"
              >
                {labLoading ? 'Attaching...' : 'Attach Investigation to Encounter'}
              </button>
            </form>
          </div>
        </div>
      )}

      {/* MODAL: Printable Multi-Device Clinical Dossier */}
      {showDossierModal && selectedPatientDossier && (
        <div className="fixed inset-0 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4 z-50">
          <div className="bg-white rounded-2xl max-w-3xl w-full p-8 shadow-2xl max-h-[90vh] flex flex-col text-slate-900">
            <div className="flex items-center justify-between pb-4 border-b border-slate-200">
              <div className="flex items-center space-x-3">
                <Building2 className="w-8 h-8 text-indigo-600" />
                <div>
                  <h2 className="text-xl font-black tracking-tight uppercase">Pulse Hospital & Critical Care Network</h2>
                  <p className="text-xs text-slate-500">Inpatient Clinical Summary & Multi-Parameter Encounter Dossier</p>
                </div>
              </div>
              <button onClick={() => setShowDossierModal(false)} className="text-slate-400 hover:text-slate-600"><X className="w-6 h-6" /></button>
            </div>

            <div className="mt-4 flex-1 overflow-y-auto space-y-6 pr-2">
              {/* Demographics */}
              <div className="bg-slate-50 p-4 rounded-xl border border-slate-200">
                <h4 className="text-xs font-bold uppercase tracking-wider text-indigo-700 mb-3 flex items-center gap-1.5">
                  <User className="w-4 h-4" /> Patient Demographics & Encounter Details
                </h4>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
                  <div><span className="text-slate-400 block text-[10px]">Patient Name</span><span className="font-bold text-sm text-slate-900">{selectedPatientDossier.patient_name}</span></div>
                  <div><span className="text-slate-400 block text-[10px]">MRN</span><span className="font-mono font-bold text-blue-700">{selectedPatientDossier.patient_mrn}</span></div>
                  <div><span className="text-slate-400 block text-[10px]">Age / Gender</span><span className="font-semibold">{selectedPatientDossier.age} Y / {selectedPatientDossier.gender}</span></div>
                  <div><span className="text-slate-400 block text-[10px]">Blood Group</span><span className="font-bold text-rose-600">{selectedPatientDossier.blood_group}</span></div>
                  <div><span className="text-slate-400 block text-[10px]">Admitted On</span><span className="font-semibold">{selectedPatientDossier.admission?.admitted_at}</span></div>
                  <div><span className="text-slate-400 block text-[10px]">Discharged On</span><span className="font-semibold">{selectedPatientDossier.admission?.discharged_at}</span></div>
                  <div><span className="text-slate-400 block text-[10px]">Admission Type</span><span className="font-semibold">{selectedPatientDossier.admission?.admission_type}</span></div>
                  <div><span className="text-slate-400 block text-[10px]">Discharge Status</span><span className="font-semibold text-emerald-700">{selectedPatientDossier.admission?.discharge_type}</span></div>
                  <div className="col-span-2"><span className="text-slate-400 block text-[10px]">Attending Consultant</span><span className="font-semibold">{selectedPatientDossier.admission?.attending_doctor}</span></div>
                  <div className="col-span-2"><span className="text-slate-400 block text-[10px]">Contact & Address</span><span className="font-semibold">{selectedPatientDossier.phone_number} | {selectedPatientDossier.address}</span></div>
                </div>
              </div>

              {/* Diagnostic Investigations */}
              <div>
                <h4 className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-3 flex items-center gap-1.5">
                  <FlaskConical className="w-4 h-4 text-emerald-600" /> Attached Diagnostic Investigations ({selectedPatientDossier.total_reports})
                </h4>
                {selectedPatientDossier.reports?.length === 0 ? (
                  <p className="text-xs text-slate-400 italic bg-slate-50 p-4 rounded-xl text-center">No diagnostic investigations recorded for this admission encounter.</p>
                ) : (
                  <div className="space-y-3">
                    {selectedPatientDossier.reports?.map((rpt: any) => (
                      <div key={rpt.report_id} className="p-3.5 bg-slate-50 rounded-xl border border-slate-200 text-xs space-y-2">
                        <div className="flex justify-between items-center">
                          <span className="font-bold text-slate-900">{rpt.test_name}</span>
                          <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-emerald-100 text-emerald-800">{rpt.department}</span>
                        </div>
                        {rpt.parameters && (
                          <div className="grid grid-cols-3 gap-2 bg-white p-2 rounded-lg border border-slate-200">
                            {Object.entries(rpt.parameters).map(([k, v]: any) => (
                              <div key={k}><span className="text-slate-400 block text-[10px]">{k}</span><span className="font-bold text-slate-800">{v}</span></div>
                            ))}
                          </div>
                        )}
                        {rpt.notes && <p className="text-slate-600 italic">"Findings: {rpt.notes}"</p>}
                        <div className="text-[10px] text-slate-400 flex justify-between pt-1 border-t border-slate-200/60">
                          <span>Recorded by: {rpt.technician}</span>
                          <span>{rpt.created_at}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Multi-Device Hardware Telemetry Summary */}
              <div className="bg-indigo-50/60 p-4 rounded-xl border border-indigo-100">
                <h4 className="text-xs font-bold uppercase tracking-wider text-indigo-800 mb-2 flex items-center gap-1.5">
                  <ShieldCheck className="w-4 h-4 text-indigo-600" /> Multi-Parameter Telemetry Delivery Audit
                </h4>
                <div className="grid grid-cols-3 gap-3 text-xs mt-2">
                  <div><span className="text-slate-500 block text-[10px]">Primary Infusion Pump</span><span className="font-mono font-bold text-slate-800">{selectedPatientDossier.telemetry_summary?.pump_id || '--'}</span></div>
                  <div><span className="text-slate-500 block text-[10px]">Total Medication Delivered</span><span className="font-bold text-indigo-700 text-sm">{selectedPatientDossier.telemetry_summary?.total_volume_ml?.toFixed(1) || '0.0'} mL</span></div>
                  <div><span className="text-slate-500 block text-[10px]">Mean Infusion Pressure</span><span className="font-bold text-slate-800 text-sm">{selectedPatientDossier.telemetry_summary?.avg_pressure_kpa || '0.0'} kPa</span></div>
                </div>
              </div>

              {/* Verification Signature */}
              <div className="pt-4 border-t border-slate-200 flex justify-between items-end text-xs text-slate-500">
                <div>
                  <p>Certified Electronic Clinical Record</p>
                  <p className="text-[10px] text-slate-400 font-mono">Encounter-UUID: {selectedPatientDossier.admission?.admission_id}</p>
                </div>
                <div className="text-center">
                  <div className="w-40 border-b border-slate-400 mb-1 pb-4 text-slate-400 italic">Medical Officer Sign</div>
                  <span className="font-bold text-slate-700">{selectedPatientDossier.admission?.attending_doctor}</span>
                </div>
              </div>
            </div>

            <div className="mt-6 pt-4 border-t border-slate-200 flex justify-between">
              <button
                onClick={() => window.print()}
                className="flex items-center space-x-1.5 px-4 py-2 bg-slate-900 text-white rounded-xl text-xs font-bold hover:bg-slate-800 transition shadow"
              >
                <Printer className="w-4 h-4" />
                <span>Print Official Hospital Dossier</span>
              </button>
              <button
                onClick={() => setShowDossierModal(false)}
                className="px-4 py-2 bg-slate-100 text-slate-700 rounded-xl text-xs font-bold hover:bg-slate-200"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* MODAL: Discharged Records */}
      {showDischargedModal && (
        <div className="fixed inset-0 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4 z-50">
          <div className="bg-slate-800 rounded-2xl max-w-4xl w-full p-6 shadow-2xl border border-slate-700 max-h-[90vh] flex flex-col">
            <div className="flex items-center justify-between pb-4 border-b border-slate-700">
              <div className="flex items-center space-x-2">
                <FolderClock className="w-5 h-5 text-amber-400" />
                <h3 className="text-lg font-bold text-white">Discharged Inpatient Records</h3>
              </div>
              <button onClick={() => setShowDischargedModal(false)} className="text-slate-400 hover:text-white"><X className="w-5 h-5" /></button>
            </div>

            <div className="mt-4 flex-1 overflow-y-auto">
              {dischargedRecords.length === 0 ? (
                <div className="p-8 text-center text-slate-400 text-sm">No historical records found.</div>
              ) : (
                <table className="w-full text-left text-xs text-slate-300">
                  <thead className="bg-slate-900 text-slate-400 font-semibold border-b border-slate-700 sticky top-0">
                    <tr>
                      <th className="p-3">Patient MRN & Name</th>
                      <th className="p-3">Bed Station</th>
                      <th className="p-3">Timeline</th>
                      <th className="p-3">Discharge Outcome</th>
                      <th className="p-3 text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-700/60">
                    {dischargedRecords.map((rec) => (
                      <tr key={rec.association_id} className="hover:bg-slate-700/40">
                        <td className="p-3 font-medium text-white">{rec.patient_name} <span className="block font-mono text-[10px] text-indigo-400">{rec.patient_id}</span></td>
                        <td className="p-3 font-semibold">{rec.bed_number}</td>
                        <td className="p-3 text-[11px] text-slate-400">
                          <div>Discharged: {rec.discharged_at ? new Date(rec.discharged_at).toLocaleDateString() : '--'}</div>
                        </td>
                        <td className="p-3 text-emerald-400 font-semibold">{rec.discharge_type || 'Routine'}</td>
                        <td className="p-3 text-right">
                          <button
                            onClick={() => {
                              setShowDischargedModal(false);
                              openDossier(rec.patient_id);
                            }}
                            className="px-2.5 py-1 text-xs font-semibold bg-indigo-950 text-indigo-300 border border-indigo-700 rounded-lg hover:bg-indigo-900"
                          >
                            Dossier
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>

            <div className="mt-4 pt-3 border-t border-slate-700 flex justify-end">
              <button onClick={() => setShowDischargedModal(false)} className="px-4 py-2 bg-slate-700 text-white rounded-xl text-xs font-bold hover:bg-slate-600">Close</button>
            </div>
          </div>
        </div>
      )}

      {/* QR Token Modal */}
      {qrTokenModal && (
        <div className="fixed inset-0 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4 z-50">
          <div className="bg-slate-800 rounded-2xl max-w-xs w-full p-6 text-center shadow-2xl border border-slate-700">
            <h3 className="text-sm font-bold text-white">{qrTokenModal.title}</h3>
            <div className="mt-4 flex justify-center p-4 bg-white rounded-xl">
              <QRCodeSVG value={qrTokenModal.value} size={150} level="H" />
            </div>
            <p className="text-[11px] text-slate-400 mt-3 font-mono break-all">{qrTokenModal.value}</p>
            <button onClick={() => setQrTokenModal(null)} className="mt-4 w-full py-2 bg-slate-700 text-white rounded-xl text-xs font-bold hover:bg-slate-600">Done</button>
          </div>
        </div>
      )}
    </main>
  );
}
