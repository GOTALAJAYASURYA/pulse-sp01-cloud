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

interface DeviceTelemetryPayload {
  device_id: string;
  device_type: DeviceType;
  timestamp: string;
  active_alarms?: string[];
  vitals?: {
    heart_rate_bpm: number;
    spo2_pct: number;
    nibp_systolic: number;
    nibp_diastolic: number;
    resp_rate_bpm: number;
    temp_c: number;
  };
  infusion_status?: {
    rate_ml_hr: number;
    vtbi_ml: number;
    volume_infused_ml: number;
    time_remaining_sec: number;
    pressure_kpa: number;
  };
  ders?: { drug_name: string };
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
  const [audioEnabled, setAudioEnabled] = useState(true);

  // Suggestions from Fleet
  const [suggestedBed, setSuggestedBed] = useState('ICU-B1');
  const [suggestedMrn, setSuggestedMrn] = useState('PTN-000001');
  const [fleetSp, setFleetSp] = useState('SP01-2026-0001');
  const [fleetPm, setFleetPm] = useState('PM01-2026-1001');
  const [fleetDl, setFleetDl] = useState('DL01-2026-5001');

  // Modals
  const [showAdmissionModal, setShowAdmissionModal] = useState(false);
  const [showAttachDeviceModal, setShowAttachDeviceModal] = useState(false);
  const [showBedQrStudio, setShowBedQrStudio] = useState(false);
  const [targetBedForDevice, setTargetBedForDevice] = useState<ActiveBed | null>(null);
  const [showDischargedModal, setShowDischargedModal] = useState(false);
  const [dischargedRecords, setDischargedRecords] = useState<any[]>([]);
  const [showLabModal, setShowLabModal] = useState(false);
  const [showDossierModal, setShowDossierModal] = useState(false);
  const [selectedPatientDossier, setSelectedPatientDossier] = useState<any>(null);
  const [qrTokenModal, setQrTokenModal] = useState<{ title: string; value: string } | null>(null);

  // Admission Form
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

  // Attach Device
  const [attachTab, setAttachTab] = useState<'AUTO' | 'CAMERA'>('AUTO');
  const [selectedDeviceType, setSelectedDeviceType] = useState<DeviceType>('SYRINGE_PUMP');
  const [deviceSerialId, setDeviceSerialId] = useState('SP01-2026-0001');
  const [deviceCameraActive, setDeviceCameraActive] = useState(false);
  const deviceQrScannerRef = useRef<Html5Qrcode | null>(null);

  // Lab Report
  const [labMrn, setLabMrn] = useState('');
  const [labDept, setLabDept] = useState('PATHOLOGY');
  const [labTestName, setLabTestName] = useState('Complete Blood Count (CBC)');
  const [labHb, setLabHb] = useState('13.2');
  const [labWbc, setLabWbc] = useState('7800');
  const [labPlatelets, setLabPlatelets] = useState('220000');
  const [labNotes, setLabNotes] = useState('');
  const [labLoading, setLabLoading] = useState(false);
  const [labCameraActive, setLabCameraActive] = useState(false);
  const labQrScannerRef = useRef<Html5Qrcode | null>(null);

  const audioCtxRef = useRef<AudioContext | null>(null);

  // Realistic Hospital Alarm Chime (IEC 60601-1-8 standard tone)
  const playHospitalAlarmSound = () => {
    if (!audioEnabled) return;
    try {
      const ctx = audioCtxRef.current || new (window.AudioContext || (window as any).webkitAudioContext)();
      audioCtxRef.current = ctx;
      if (ctx.state === 'suspended') ctx.resume();

      const tones = [523.25, 659.25, 783.99]; // C5 - E5 - G5 medical alert sequence
      tones.forEach((freq, idx) => {
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.type = 'sine';
        osc.frequency.setValueAtTime(freq, ctx.currentTime + idx * 0.12);
        gain.gain.setValueAtTime(0.2, ctx.currentTime + idx * 0.12);
        gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + idx * 0.12 + 0.1);
        osc.connect(gain);
        gain.connect(ctx.destination);
        osc.start(ctx.currentTime + idx * 0.12);
        osc.stop(ctx.currentTime + idx * 0.12 + 0.1);
      });
    } catch (e) {}
  };

  const fetchRegistry = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/v1/registry-status`);
      if (res.ok) {
        const data = await res.json();
        setBeds(data.active_associations || data.beds || []);
        if (data.next_suggestions) {
          setSuggestedBed(data.next_suggestions.bed);
          setSuggestedMrn(data.next_suggestions.mrn);
          setFormBed(data.next_suggestions.bed);
          setFormMrn(data.next_suggestions.mrn);
          setFleetSp(data.next_suggestions.sp);
          setFleetPm(data.next_suggestions.pm);
          setFleetDl(data.next_suggestions.dl);
        }
      }
    } catch (e) {
      console.error('Failed to fetch registry', e);
    }
  };

  useEffect(() => {
    fetchRegistry();
  }, []);

  // Update selected hardware suggestion on device type switch
  useEffect(() => {
    if (selectedDeviceType === 'SYRINGE_PUMP') setDeviceSerialId(fleetSp);
    else if (selectedDeviceType === 'PATIENT_MONITOR') setDeviceSerialId(fleetPm);
    else if (selectedDeviceType === 'DIALYSIS') setDeviceSerialId(fleetDl);
  }, [selectedDeviceType, fleetSp, fleetPm, fleetDl]);

  // WebSocket Live Updates
  useEffect(() => {
    const ws = new WebSocket(WS_BASE);
    ws.onopen = () => setConnected(true);
    ws.onclose = () => setConnected(false);
    ws.onmessage = (event) => {
      try {
        const data: DeviceTelemetryPayload = JSON.parse(event.data);
        setTelemetry((prev) => ({ ...prev, [data.device_id]: data }));
        if (data.active_alarms && data.active_alarms.length > 0) {
          playHospitalAlarmSound();
        }
      } catch (err) {}
    };
    return () => ws.close();
  }, [audioEnabled]);

  // Patient Admission
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

  // Device Binding
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
        if (deviceQrScannerRef.current?.isScanning) await deviceQrScannerRef.current.stop();
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

  // Unbind Single Device
  const handleUnbindDevice = async (deviceId: string, bedNumber: string) => {
    if (!confirm(`Release equipment ${deviceId} from Bed ${bedNumber}? Equipment will return to available inventory.`)) return;
    try {
      const res = await fetch(`${API_BASE}/api/v1/devices/unbind`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ device_id: deviceId })
      });
      if (res.ok) await fetchRegistry();
    } catch (err) {
      alert('Network error releasing device.');
    }
  };

  // Discharge Patient
  const handleDischargePatient = async (bed: ActiveBed) => {
    const dischargeReason = prompt(
      `Discharge patient ${bed.patient_name} (${bed.patient_mrn})?\nEnter outcome: 1. Routine / Recovered 2. Transferred 3. DOR`, 
      "Routine / Recovered"
    );
    if (!dischargeReason) return;

    try {
      await fetch(`${API_BASE}/api/v1/discharge-encounter`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ bed_number: bed.bed_number, patient_mrn: bed.patient_mrn, discharge_type: dischargeReason })
      });
      await fetchRegistry();
    } catch (err) {
      alert('Error discharging patient.');
    }
  };

  return (
    <main className="min-h-screen bg-slate-900 text-slate-100 p-6 font-sans">
      {/* Header */}
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
            ICU Fleet: {beds.length} Active Bed Encounters | Real-time Multi-Hardware Monitoring Station
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2.5">
          <button
            onClick={() => {
              setLabMrn(beds[0]?.patient_mrn || '');
              setShowLabModal(true);
            }}
            className="flex items-center space-x-1.5 px-3.5 py-2 rounded-xl text-xs font-bold bg-emerald-600 text-white hover:bg-emerald-500 transition shadow"
          >
            <FlaskConical className="w-4 h-4" />
            <span>Attach Lab/Scan</span>
          </button>

          <button
            onClick={async () => {
              const res = await fetch(`${API_BASE}/api/v1/discharged-records`);
              if (res.ok) {
                setDischargedRecords(await res.json());
                setShowDischargedModal(true);
              }
            }}
            className="flex items-center space-x-1.5 px-3.5 py-2 rounded-xl text-xs font-bold bg-amber-600 text-white hover:bg-amber-500 transition shadow"
          >
            <FolderClock className="w-4 h-4" />
            <span>Discharged Records</span>
          </button>

          <button
            onClick={() => setShowBedQrStudio(true)}
            className="flex items-center space-x-1.5 px-3.5 py-2 rounded-xl text-xs font-bold bg-violet-600 text-white hover:bg-violet-500 transition shadow"
          >
            <Sparkles className="w-4 h-4 text-violet-200" />
            <span>Auto-Pairing Studio (QRs)</span>
          </button>

          <button
            onClick={() => {
              setFormBed(suggestedBed);
              setFormMrn(suggestedMrn);
              setShowAdmissionModal(true);
            }}
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

      {/* Bed Stations Grid */}
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
                        onClick={async () => {
                          const res = await fetch(`${API_BASE}/api/v1/patient-dossier/${b.patient_mrn}`);
                          if (res.ok) {
                            setSelectedPatientDossier(await res.json());
                            setShowDossierModal(true);
                          }
                        }}
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
                        setSelectedDeviceType('SYRINGE_PUMP');
                        setDeviceSerialId(fleetSp);
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

                      // Patient Monitor Bay
                      if (dev.device_type === 'PATIENT_MONITOR') {
                        const hr = live?.vitals?.heart_rate_bpm ?? 76;
                        const spo2 = live?.vitals?.spo2_pct ?? 99;
                        const sys = live?.vitals?.nibp_systolic ?? 120;
                        const dia = live?.vitals?.nibp_diastolic ?? 80;
                        const resp = live?.vitals?.resp_rate_bpm ?? 16;
                        const temp = live?.vitals?.temp_c ?? 36.8;

                        return (
                          <div key={dev.device_id} className={`p-3 rounded-xl border transition ${hasAlarm ? 'bg-red-950/70 border-red-500 shadow-[0_0_12px_#ef4444]' : 'bg-slate-900/80 border-emerald-900/60'}`}>
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
                            {hasAlarm && (
                              <div className="mt-2 text-[11px] font-bold text-red-400 flex items-center gap-1 animate-pulse">
                                <AlertTriangle className="w-3.5 h-3.5" /> {live?.active_alarms?.join(', ')}
                              </div>
                            )}
                          </div>
                        );
                      }

                      // Syringe Pump Bay
                      if (dev.device_type === 'SYRINGE_PUMP') {
                        const drug = live?.ders?.drug_name || 'Norepinephrine';
                        const rate = live?.infusion_status?.rate_ml_hr ?? 5.0;
                        const delivered = live?.infusion_status?.volume_infused_ml ?? 8.5;
                        const vtbi = live?.infusion_status?.vtbi_ml ?? 50.0;
                        const pressure = live?.infusion_status?.pressure_kpa ?? 39.5;
                        const pct = Math.min(100, Math.round((delivered / (vtbi || 50)) * 100));

                        return (
                          <div key={dev.device_id} className={`p-3 rounded-xl border transition ${hasAlarm ? 'bg-red-950/70 border-red-500 shadow-[0_0_12px_#ef4444]' : 'bg-slate-900/80 border-indigo-900/60'}`}>
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
                            {hasAlarm && (
                              <div className="mt-2 text-[11px] font-bold text-red-400 flex items-center gap-1 animate-pulse">
                                <AlertTriangle className="w-3.5 h-3.5" /> {live?.active_alarms?.join(', ')}
                              </div>
                            )}
                          </div>
                        );
                      }

                      // Dialysis Bay
                      if (dev.device_type === 'DIALYSIS') {
                        const bfr = live?.dialysis_metrics?.blood_flow_ml_min ?? 250;
                        const ufr = live?.dialysis_metrics?.uf_rate_ml_hr ?? 300;
                        const totalUf = live?.dialysis_metrics?.total_uf_removed_ml ?? 1200;
                        const vp = live?.dialysis_metrics?.venous_pressure_mmhg ?? 110;

                        return (
                          <div key={dev.device_id} className={`p-3 rounded-xl border transition ${hasAlarm ? 'bg-red-950/70 border-red-500 shadow-[0_0_12px_#ef4444]' : 'bg-slate-900/80 border-rose-900/60'}`}>
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
                                <span className="text-[9px] text-slate-400 block uppercase">Venous P</span>
                                <span className="text-xs font-black text-emerald-400">{vp} mmHg</span>
                              </div>
                            </div>
                            {hasAlarm && (
                              <div className="mt-2 text-[11px] font-bold text-red-400 flex items-center gap-1 animate-pulse">
                                <AlertTriangle className="w-3.5 h-3.5" /> {live?.active_alarms?.join(', ')}
                              </div>
                            )}
                          </div>
                        );
                      }

                      return null;
                    })
                  )}
                </div>
              </div>

              {/* Card Footer */}
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

      {/* MODAL: Admit Patient */}
      {showAdmissionModal && (
        <div className="fixed inset-0 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4 z-50">
          <div className="bg-slate-800 rounded-2xl max-w-xl w-full p-6 shadow-2xl border border-slate-700 max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between pb-4 border-b border-slate-700">
              <div>
                <h3 className="text-lg font-bold text-white">Patient Clinical Admission</h3>
                <p className="text-xs text-slate-400">Assign inpatient to bed station (Duplication protected).</p>
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
                  <label className="block text-xs font-bold text-slate-300 mb-1">Patient MRN</label>
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
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-bold text-slate-300 mb-1">Attending Doctor</label>
                  <input value={formDoctor} onChange={(e) => setFormDoctor(e.target.value)} required className="w-full px-3 py-2 rounded-xl bg-slate-900 border border-slate-700 text-sm text-white focus:outline-none" />
                </div>
              </div>

              <button type="submit" className="w-full py-2.5 bg-indigo-600 hover:bg-indigo-500 text-white rounded-xl text-sm font-bold transition shadow">
                Complete Inpatient Admission
              </button>
            </form>
          </div>
        </div>
      )}

      {/* MODAL: Auto-Pairing Studio (QRs for Bed, Patient, and Hardware) */}
      {showBedQrStudio && (
        <div className="fixed inset-0 bg-black/75 backdrop-blur-sm flex items-center justify-center p-4 z-50">
          <div className="bg-slate-800 rounded-2xl max-w-2xl w-full p-6 shadow-2xl border border-slate-700 max-h-[92vh] overflow-y-auto">
            <div className="flex items-center justify-between pb-3 border-b border-slate-700">
              <div className="flex items-center space-x-2">
                <Sparkles className="w-5 h-5 text-violet-400" />
                <h3 className="text-base font-bold text-white">Smart Fleet & Equipment Allocation Studio</h3>
              </div>
              <button onClick={() => setShowBedQrStudio(false)} className="text-slate-400 hover:text-white">
                <X className="w-5 h-5" />
              </button>
            </div>

            <p className="text-xs text-slate-400 mt-2">
              Lowest free bed, patient MRN, and hardware serials automatically selected from hospital inventory.
            </p>

            <div className="grid grid-cols-3 gap-3 mt-4">
              <div className="p-3 bg-slate-900 rounded-xl border border-slate-700 text-center flex flex-col items-center">
                <span className="text-[10px] font-bold text-emerald-400 uppercase">Available Bed</span>
                <p className="text-sm font-black text-white mt-0.5">{suggestedBed}</p>
                <div className="p-2 bg-white rounded-lg mt-2">
                  <QRCodeSVG value={`BED:${suggestedBed}`} size={85} level="H" />
                </div>
                <span className="text-[9px] font-mono text-slate-400 mt-1">BED:{suggestedBed}</span>
              </div>

              <div className="p-3 bg-slate-900 rounded-xl border border-slate-700 text-center flex flex-col items-center">
                <span className="text-[10px] font-bold text-cyan-400 uppercase">Available MRN</span>
                <p className="text-sm font-black text-white mt-0.5">{suggestedMrn}</p>
                <div className="p-2 bg-white rounded-lg mt-2">
                  <QRCodeSVG value={`MRN:${suggestedMrn}`} size={85} level="H" />
                </div>
                <span className="text-[9px] font-mono text-slate-400 mt-1">MRN:{suggestedMrn}</span>
              </div>

              <div className="p-3 bg-slate-900 rounded-xl border border-slate-700 text-center flex flex-col items-center">
                <span className="text-[10px] font-bold text-indigo-400 uppercase">Next Free SP</span>
                <p className="text-sm font-black text-white mt-0.5">{fleetSp}</p>
                <div className="p-2 bg-white rounded-lg mt-2">
                  <QRCodeSVG value={`PUMP:${fleetSp}`} size={85} level="H" />
                </div>
                <span className="text-[9px] font-mono text-slate-400 mt-1">PUMP:{fleetSp}</span>
              </div>
            </div>

            <div className="mt-4 p-4 bg-slate-900 rounded-xl border border-slate-700 flex flex-col items-center justify-center">
              <span className="text-xs font-bold text-violet-300 mb-2">Combination Bed + Patient Pairing Token</span>
              <div className="p-2 bg-white rounded-lg">
                <QRCodeSVG value={`BED:${suggestedBed}|MRN:${suggestedMrn}`} size={120} level="H" />
              </div>
              <span className="text-[10px] font-mono text-slate-400 mt-2">BED:{suggestedBed}|MRN:{suggestedMrn}</span>
            </div>

            <div className="mt-5 flex gap-2">
              <button
                type="button"
                onClick={() => {
                  setFormBed(suggestedBed);
                  setFormMrn(suggestedMrn);
                  setShowBedQrStudio(false);
                  setShowAdmissionModal(true);
                }}
                className="flex-1 py-3 bg-violet-600 hover:bg-violet-500 text-white rounded-xl text-xs font-bold transition shadow flex items-center justify-center gap-2"
              >
                <span>🚀 Bind {suggestedBed} & {suggestedMrn} → Admit Patient</span>
              </button>
              <button
                type="button"
                onClick={() => setShowBedQrStudio(false)}
                className="px-4 py-3 bg-slate-700 text-slate-300 rounded-xl text-xs font-bold hover:bg-slate-600"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* MODAL: Attach Device to Patient Bed */}
      {showAttachDeviceModal && targetBedForDevice && (
        <div className="fixed inset-0 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4 z-50">
          <div className="bg-slate-800 rounded-2xl max-w-md w-full p-6 shadow-2xl border border-slate-700">
            <div className="flex items-center justify-between pb-3 border-b border-slate-700">
              <div>
                <h3 className="text-base font-bold text-white">Attach Telemetry Equipment</h3>
                <p className="text-xs text-slate-400">Target: {targetBedForDevice.bed_number} ({targetBedForDevice.patient_name})</p>
              </div>
              <button onClick={() => setShowAttachDeviceModal(false)} className="text-slate-400 hover:text-white">
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="mt-4 space-y-4">
              <div>
                <label className="block text-xs font-bold text-slate-300 mb-1">Select Hardware Type</label>
                <select
                  value={selectedDeviceType}
                  onChange={(e) => setSelectedDeviceType(e.target.value as DeviceType)}
                  className="w-full px-3 py-2 rounded-xl bg-slate-900 border border-slate-700 text-sm text-white focus:outline-none"
                >
                  <option value="SYRINGE_PUMP">💉 Syringe Pump ({fleetSp} Available)</option>
                  <option value="PATIENT_MONITOR">🫀 Patient Monitor ({fleetPm} Available)</option>
                  <option value="DIALYSIS">🩸 Dialysis Unit ({fleetDl} Available)</option>
                </select>
              </div>

              <div>
                <label className="block text-xs font-bold text-slate-300 mb-1">Hardware Serial ID (Auto-Allocated)</label>
                <input
                  value={deviceSerialId}
                  onChange={(e) => setDeviceSerialId(e.target.value)}
                  required
                  className="w-full px-3 py-2 rounded-xl bg-slate-900 border border-slate-700 text-sm font-mono text-indigo-300 focus:outline-none"
                />
              </div>

              <div className="p-4 bg-slate-900 rounded-xl border border-slate-700 flex flex-col items-center justify-center">
                <span className="text-[11px] text-slate-400 font-semibold mb-2">Equipment Chassis QR</span>
                <div className="p-2 bg-white rounded-lg">
                  <QRCodeSVG value={`${selectedDeviceType}:${deviceSerialId}`} size={120} level="H" />
                </div>
                <span className="text-[10px] font-mono text-slate-400 mt-2">{selectedDeviceType}:{deviceSerialId}</span>
              </div>

              <button
                type="button"
                onClick={() => handleAttachDeviceSubmit()}
                className="w-full py-2.5 bg-indigo-600 hover:bg-indigo-500 text-white rounded-xl text-sm font-bold transition shadow"
              >
                Confirm & Bind Equipment to Bed
              </button>
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
