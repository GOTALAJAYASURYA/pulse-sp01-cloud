'use client';

import React, { useEffect, useState, useRef } from 'react';
import { QRCodeSVG } from 'qrcode.react';
import { ResponsiveContainer, AreaChart, Area, XAxis, YAxis, Tooltip, CartesianGrid } from 'recharts';
import { 
  ShieldCheck, Volume2, VolumeX, QrCode, 
  AlertTriangle, CheckCircle2, X, History, Camera, LogOut, 
  Sparkles, UserPlus, FolderClock, Upload, FlaskConical, FileText, Printer, Building2, User
} from 'lucide-react';
import { Html5Qrcode } from 'html5-qrcode';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'https://pulse-sp01-backend.onrender.com';
const WS_BASE = process.env.NEXT_PUBLIC_WS_URL || 'wss://pulse-sp01-backend.onrender.com/ws/telemetry';

interface ActiveBed {
  association_id: string;
  pump_id: string;
  bed_number: string;
  patient_mrn: string;
  patient_name: string;
  paired_at: string;
  age?: number;
  gender?: string;
  blood_group?: string;
  admission_type?: string;
  attending_doctor?: string;
}

interface DischargedRecord {
  association_id: string;
  patient_id: string;
  patient_name: string;
  bed_number: string;
  pump_id: string;
  paired_at: string;
  discharged_at: string;
  discharge_type?: string;
  total_volume_ml: number;
  avg_pressure_kpa: number;
  session_points: number;
}

interface TelemetryPayload {
  pump_id: string;
  timestamp: string;
  infusion_status: {
    rate_ml_hr: number;
    vtbi_ml: number;
    volume_infused_ml: number;
    time_remaining_sec: number;
    pressure_kpa: number;
  };
  ders: {
    drug_name: string;
  };
  active_alarms: string[];
}

export default function SmartWardCentral() {
  const [beds, setBeds] = useState<ActiveBed[]>([]);
  const [busyPumps, setBusyPumps] = useState<string[]>([]);
  const [telemetry, setTelemetry] = useState<Record<string, TelemetryPayload>>({});
  const [connected, setConnected] = useState(false);
  const [audioEnabled, setAudioEnabled] = useState(false);
  
  // Modals
  const [showPairModal, setShowPairModal] = useState(false);
  const [showCameraScanner, setShowCameraScanner] = useState(false);
  const [showQrStudio, setShowQrStudio] = useState(false);
  const [showDischargedModal, setShowDischargedModal] = useState(false);
  const [dischargedRecords, setDischargedRecords] = useState<DischargedRecord[]>([]);
  const [qrTokenModal, setQrTokenModal] = useState<{ title: string; value: string } | null>(null);
  const [selectedHistoryPump, setSelectedHistoryPump] = useState<string | null>(null);
  const [historyLogs, setHistoryLogs] = useState<any[]>([]);
  const [scanStatus, setScanStatus] = useState<string>('Initializing Camera...');

  // Lab & Dossier States
  const [showLabModal, setShowLabModal] = useState(false);
  const [showDossierModal, setShowDossierModal] = useState(false);
  const [selectedPatientDossier, setSelectedPatientDossier] = useState<any>(null);
  const [labMrn, setLabMrn] = useState('');
  const [labDept, setLabDept] = useState('PATHOLOGY');
  const [labTestName, setLabTestName] = useState('Complete Blood Count (CBC)');
  const [labHb, setLabHb] = useState('13.2');
  const [labWbc, setLabWbc] = useState('7800');
  const [labPlatelets, setLabPlatelets] = useState('220000');
  const [labNotes, setLabNotes] = useState('');
  const [labLoading, setLabLoading] = useState(false);

  // Form States (Hospital Clinical Intake)
  const [formBed, setFormBed] = useState('ICU-B1');
  const [formMrn, setFormMrn] = useState('PTN-000001');
  const [formName, setFormName] = useState('RAGHU');
  const [formPump, setFormPump] = useState('SP01-2026-0001');
  const [formAge, setFormAge] = useState<number>(45);
  const [formGender, setFormGender] = useState('Male');
  const [formBloodGroup, setFormBloodGroup] = useState('O+');
  const [formPhone, setFormPhone] = useState('+91 98765 43210');
  const [formAddress, setFormAddress] = useState('Flat 402, Green Meadows, Vizag');
  const [formAdmissionType, setFormAdmissionType] = useState('Emergency');
  const [formDoctor, setFormDoctor] = useState('Dr. Robert Vance');
  const [formDiagnosis, setFormDiagnosis] = useState('Acute Hemodynamic Monitoring');

  const audioCtxRef = useRef<AudioContext | null>(null);
  const html5QrCodeRef = useRef<Html5Qrcode | null>(null);

  const fetchRegistry = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/v1/registry-status`);
      if (res.ok) {
        const data = await res.json();
        setBeds(data.active_associations || []);
        setBusyPumps(data.busy_pumps || []);
        if (data.next_suggestions) {
          setFormBed(data.next_suggestions.bed);
          setFormMrn(data.next_suggestions.mrn);
          setFormPump(data.next_suggestions.pump);
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

  useEffect(() => {
    const ws = new WebSocket(WS_BASE);
    ws.onopen = () => setConnected(true);
    ws.onclose = () => setConnected(false);
    ws.onmessage = (event) => {
      try {
        const data: TelemetryPayload = JSON.parse(event.data);
        setTelemetry((prev) => ({ ...prev, [data.pump_id]: data }));
        if (data.active_alarms && data.active_alarms.length > 0) {
          playAlarmTone();
        }
      } catch (err) {}
    };
    return () => ws.close();
  }, [audioEnabled]);

  const handleDecodedString = async (decodedText: string) => {
    let bed = formBed;
    let mrn = formMrn;
    let name = formName;
    let pump = formPump;

    if (decodedText.includes('|')) {
      const parts = decodedText.split('|');
      parts.forEach((p) => {
        const [k, v] = p.split(':');
        if (k === 'BED') bed = v;
        if (k === 'MRN') mrn = v;
        if (k === 'NAME') name = v;
        if (k === 'PUMP') pump = v;
      });
    } else if (decodedText.startsWith('PUMP:')) {
      pump = decodedText.replace('PUMP:', '');
    } else if (decodedText.startsWith('BED:')) {
      bed = decodedText.replace('BED:', '');
    } else if (decodedText.startsWith('MRN:')) {
      mrn = decodedText.replace('MRN:', '');
    }

    setFormBed(bed);
    setFormMrn(mrn);
    setFormName(name);
    setFormPump(pump);

    if (html5QrCodeRef.current?.isScanning) {
      await html5QrCodeRef.current.stop();
    }
    setShowCameraScanner(false);
    setShowPairModal(true);
  };

  useEffect(() => {
    if (!showCameraScanner) return;
    setScanStatus('Requesting Camera Access...');

    const qrScannerId = 'custom-qr-reader';
    const timer = setTimeout(async () => {
      try {
        const html5QrCode = new Html5Qrcode(qrScannerId);
        html5QrCodeRef.current = html5QrCode;

        await html5QrCode.start(
          { facingMode: 'environment' },
          { fps: 15, qrbox: { width: 250, height: 250 } },
          (decodedText) => {
            handleDecodedString(decodedText);
          },
          () => {}
        );
        setScanStatus('Camera Active: Point at QR Code');
      } catch (err: any) {
        setScanStatus('Camera unavailable. You can upload a QR image below.');
      }
    }, 200);

    return () => {
      clearTimeout(timer);
      if (html5QrCodeRef.current && html5QrCodeRef.current.isScanning) {
        html5QrCodeRef.current.stop().catch(() => {});
      }
    };
  }, [showCameraScanner]);

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    try {
      const html5QrCode = html5QrCodeRef.current || new Html5Qrcode('custom-qr-reader');
      const decodedText = await html5QrCode.scanFile(file, true);
      handleDecodedString(decodedText);
    } catch (err) {
      alert('Could not decode QR code from this image.');
    }
  };

  const handlePair = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const res = await fetch(`${API_BASE}/api/v1/pair`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          bed_number: formBed,
          patient_mrn: formMrn,
          patient_name: formName.trim(),
          pump_id: formPump,
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
        setShowPairModal(false);
        setShowQrStudio(false);
        await fetchRegistry();
      } else {
        alert(data.detail || data.message || 'Error admitting patient');
      }
    } catch (err) {
      alert('Network error connecting to backend.');
    }
  };

  const handleDischarge = async (pumpId: string) => {
    const dischargeReason = prompt(
      "Enter Discharge Type:\n1. Routine / Recovered\n2. Referred / Transferred\n3. Discharged on Request (DOR)\n4. LAMA", 
      "Routine / Recovered"
    );
    if (!dischargeReason) return;

    try {
      await fetch(`${API_BASE}/api/v1/discharge`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pump_id: pumpId, discharge_type: dischargeReason })
      });
      fetchRegistry();
    } catch (err) {
      alert('Error discharging pump');
    }
  };

  const openHistoryModal = async (pumpId: string) => {
    setSelectedHistoryPump(pumpId);
    try {
      const res = await fetch(`${API_BASE}/api/v1/history/${pumpId}`);
      if (res.ok) {
        const data = await res.json();
        setHistoryLogs(data);
      }
    } catch (e) {}
  };

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
            : { 'Scan Modality': labTestName, 'Clinical Findings': labNotes },
          technician_notes: labNotes,
          technician_name: 'Central Diagnostic Wing'
        })
      });
      const data = await res.json();
      if (res.ok && data.status === 'success') {
        alert('Diagnostic Report attached to patient record.');
        setShowLabModal(false);
        setLabNotes('');
      } else {
        alert(data.detail || data.message || 'Failed to attach report.');
      }
    } catch (err: any) {
      alert(`Network Error: ${err.message}`);
    } finally {
      setLabLoading(false);
    }
  };

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
      alert('Error fetching patient dossier.');
    }
  };

  const generatedCompositeQr = `BED:${formBed}|MRN:${formMrn}|NAME:${formName}|PUMP:${formPump}`;

  return (
    <main className="min-h-screen bg-slate-100 p-8 font-sans">
      {/* Top Clinical Header */}
      <header className="mb-8 flex flex-col lg:flex-row lg:items-center justify-between gap-4 bg-white p-6 rounded-2xl border border-slate-200 shadow-sm">
        <div>
          <div className="flex items-center space-x-3">
            <h1 className="text-2xl font-black text-slate-900 tracking-tight">Pulse SP-01 Central Telemetry</h1>
            <span className="flex items-center text-xs font-semibold px-2.5 py-1 rounded-full bg-emerald-50 text-emerald-700 border border-emerald-200">
              <ShieldCheck className="w-3.5 h-3.5 mr-1" /> Smart Ward Central
            </span>
          </div>
          <p className="text-sm text-slate-500 mt-1">
            ICU Fleet View: {beds.length} Active Bed Sessions | {busyPumps.length} Active Pumps
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <button
            onClick={() => {
              setLabMrn(beds[0]?.patient_mrn || '');
              setShowLabModal(true);
            }}
            className="flex items-center space-x-1.5 px-3.5 py-2 rounded-xl text-xs font-bold bg-emerald-600 text-white hover:bg-emerald-700 transition shadow-sm"
          >
            <FlaskConical className="w-4 h-4" />
            <span>Attach Lab/Scan</span>
          </button>

          <button
            onClick={fetchDischargedRecords}
            className="flex items-center space-x-1.5 px-3.5 py-2 rounded-xl text-xs font-bold bg-amber-600 text-white hover:bg-amber-700 transition shadow-sm"
          >
            <FolderClock className="w-4 h-4" />
            <span>Discharged Records</span>
          </button>

          <button
            onClick={() => setShowQrStudio(true)}
            className="flex items-center space-x-1.5 px-3.5 py-2 rounded-xl text-xs font-bold bg-violet-600 text-white hover:bg-violet-700 transition shadow-sm"
          >
            <Sparkles className="w-4 h-4" />
            <span>QR Studio</span>
          </button>

          <button
            onClick={() => setShowCameraScanner(true)}
            className="flex items-center space-x-1.5 px-3.5 py-2 rounded-xl text-xs font-bold bg-slate-800 text-white hover:bg-slate-900 transition shadow-sm"
          >
            <Camera className="w-4 h-4 text-emerald-400" />
            <span>Scan QR by Camera</span>
          </button>

          <button
            onClick={() => setShowPairModal(true)}
            className="flex items-center space-x-1.5 px-3.5 py-2 rounded-xl text-xs font-bold bg-indigo-600 text-white hover:bg-indigo-700 transition shadow-sm"
          >
            <UserPlus className="w-4 h-4" />
            <span>Assign New Patient</span>
          </button>

          <button
            onClick={() => setAudioEnabled(!audioEnabled)}
            className={`flex items-center space-x-1.5 px-3.5 py-2 rounded-xl text-xs font-bold border transition ${
              audioEnabled ? 'bg-amber-50 text-amber-700 border-amber-300' : 'bg-slate-50 text-slate-600 border-slate-200'
            }`}
          >
            {audioEnabled ? <Volume2 className="w-4 h-4 text-amber-600" /> : <VolumeX className="w-4 h-4 text-slate-400" />}
            <span>{audioEnabled ? 'Alarm: ON' : 'Alarm: MUTED'}</span>
          </button>

          <div className="flex items-center space-x-2 px-3 py-2 bg-slate-50 rounded-xl border border-slate-200">
            <span className={`w-3 h-3 rounded-full ${connected ? 'bg-emerald-500' : 'bg-red-500 animate-pulse'}`} />
            <span className="text-xs font-mono font-medium text-slate-600">
              {connected ? 'WS: LIVE' : 'WS: OFFLINE'}
            </span>
          </div>
        </div>
      </header>

      {/* Ward Beds Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {beds.map((b) => {
          const live = telemetry[b.pump_id];
          const hasAlarm = live?.active_alarms && live.active_alarms.length > 0;
          const rate = live ? live.infusion_status.rate_ml_hr : 0.0;
          const delivered = live ? live.infusion_status.volume_infused_ml : 0.0;
          const vtbi = live ? live.infusion_status.vtbi_ml : 50.0;
          const pressure = live ? live.infusion_status.pressure_kpa : 0.0;
          const drug = live ? live.ders.drug_name : 'Norepinephrine';
          const pct = Math.min(100, Math.round((delivered / (vtbi || 50)) * 100));

          return (
            <div
              key={b.association_id}
              className={`bg-white rounded-2xl border transition-all duration-300 shadow-sm p-6 flex flex-col justify-between ${
                hasAlarm ? 'border-red-500 ring-4 ring-red-100' : 'border-slate-200 hover:border-slate-300'
              }`}
            >
              <div>
                <div className="flex items-center justify-between pb-3 border-b border-slate-100">
                  <div className="flex items-center space-x-2">
                    <span className="text-xl font-black text-slate-900">{b.bed_number}</span>
                    <span className="px-2 py-0.5 text-xs font-mono font-semibold bg-blue-50 text-blue-700 rounded-md border border-blue-200">
                      {b.patient_mrn}
                    </span>
                  </div>
                  <div className="flex items-center space-x-1">
                    <button 
                      onClick={() => openDossier(b.patient_mrn)}
                      title="View Complete Clinical Dossier"
                      className="p-1.5 text-slate-400 hover:text-indigo-600 rounded-lg hover:bg-slate-100"
                    >
                      <FileText className="w-4 h-4" />
                    </button>
                    <button 
                      onClick={() => setQrTokenModal({ title: `${b.bed_number} Composite Token`, value: `BED:${b.bed_number}|MRN:${b.patient_mrn}|NAME:${b.patient_name}|PUMP:${b.pump_id}` })} 
                      title="View QR Token"
                      className="p-1.5 text-slate-400 hover:text-slate-600 rounded-lg hover:bg-slate-100"
                    >
                      <QrCode className="w-4 h-4" />
                    </button>
                    <button 
                      onClick={() => openHistoryModal(b.pump_id)} 
                      title="View TimescaleDB History"
                      className="p-1.5 text-slate-400 hover:text-slate-600 rounded-lg hover:bg-slate-100"
                    >
                      <History className="w-4 h-4" />
                    </button>
                  </div>
                </div>

                <div className="mt-3 flex justify-between items-start">
                  <div>
                    <h2 className="text-sm font-bold text-slate-800">{b.patient_name}</h2>
                    <div className="text-[11px] text-slate-500 mt-0.5">
                      <span>{b.age || 45} Y / {b.gender || 'M'}</span> • <span className="font-semibold text-rose-600">{b.blood_group || 'O+'}</span>
                    </div>
                    <span className="text-xs text-slate-400 font-mono block mt-1">Pump: {b.pump_id}</span>
                  </div>
                  <button
                    onClick={() => {
                      setLabMrn(b.patient_mrn);
                      setShowLabModal(true);
                    }}
                    className="text-[11px] font-bold text-emerald-700 bg-emerald-50 hover:bg-emerald-100 border border-emerald-200 px-2 py-1 rounded-lg transition flex items-center gap-1"
                  >
                    <FlaskConical className="w-3 h-3" /> + Lab/Scan
                  </button>
                </div>

                <div className={`mt-4 p-4 rounded-xl border ${hasAlarm ? 'bg-red-50 border-red-200' : 'bg-slate-50 border-slate-100'}`}>
                  <div className="flex items-center justify-between">
                    <div>
                      <span className="text-xs font-bold uppercase tracking-wider text-indigo-700">{drug}</span>
                      <p className="text-xs text-slate-500 font-mono">Pressure: {pressure} kPa</p>
                    </div>
                    <div className="text-right">
                      <span className="text-2xl font-black text-slate-900">{rate.toFixed(1)}</span>
                      <span className="text-xs text-slate-500 ml-1 font-semibold">mL/h</span>
                    </div>
                  </div>

                  <div className="mt-3">
                    <div className="h-2 w-full bg-slate-200 rounded-full overflow-hidden">
                      <div className={`h-full transition-all duration-500 ${hasAlarm ? 'bg-red-500' : 'bg-blue-600'}`} style={{ width: `${pct}%` }} />
                    </div>
                    <div className="flex justify-between text-[11px] font-mono text-slate-500 mt-1.5">
                      <span>{delivered.toFixed(1)} / {vtbi} mL ({pct}%)</span>
                      <span>{live ? `${Math.floor(live.infusion_status.time_remaining_sec / 3600)}h ${Math.floor((live.infusion_status.time_remaining_sec % 3600) / 60)}m left` : '--'}</span>
                    </div>
                  </div>
                </div>

                {hasAlarm ? (
                  <div className="mt-3 flex items-center space-x-1.5 text-xs font-bold text-red-600 animate-pulse">
                    <AlertTriangle className="w-4 h-4" />
                    <span>ALARM: {live?.active_alarms.join(', ')}</span>
                  </div>
                ) : (
                  <div className="mt-3 flex items-center space-x-1.5 text-xs font-medium text-emerald-600">
                    <CheckCircle2 className="w-3.5 h-3.5" />
                    <span>Normal Delivery Profile</span>
                  </div>
                )}
              </div>

              <div className="mt-6 pt-3 border-t border-slate-100 flex items-center justify-between">
                <span className="text-[11px] text-slate-400">Paired: {b.paired_at ? new Date(b.paired_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : 'Active'}</span>
                <div className="flex gap-1.5">
                  <button
                    onClick={() => openDossier(b.patient_mrn)}
                    className="text-xs font-semibold text-indigo-700 bg-indigo-50 hover:bg-indigo-100 px-2.5 py-1 rounded-lg border border-indigo-200 transition"
                  >
                    Dossier
                  </button>
                  <button
                    onClick={() => handleDischarge(b.pump_id)}
                    className="flex items-center space-x-1 text-xs font-semibold text-rose-600 hover:text-rose-700 bg-rose-50 px-2.5 py-1 rounded-lg border border-rose-200 hover:bg-rose-100 transition"
                  >
                    <LogOut className="w-3.5 h-3.5" />
                    <span>Discharge</span>
                  </button>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* MODAL: Clinical Inpatient Admission (Demographics & Vitals) */}
      {showPairModal && (
        <div className="fixed inset-0 bg-slate-900/60 backdrop-blur-sm flex items-center justify-center p-4 z-50">
          <div className="bg-white rounded-2xl max-w-xl w-full p-6 shadow-2xl border border-slate-100 max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between pb-4 border-b border-slate-100">
              <div>
                <h3 className="text-lg font-bold text-slate-900">Patient Clinical Admission</h3>
                <p className="text-xs text-slate-500">Record full inpatient demographic & encounter details.</p>
              </div>
              <button onClick={() => setShowPairModal(false)} className="text-slate-400 hover:text-slate-600"><X className="w-5 h-5" /></button>
            </div>

            <form onSubmit={handlePair} className="mt-4 space-y-4">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-bold text-slate-700 mb-1">ICU Bed Station</label>
                  <input value={formBed} onChange={(e) => setFormBed(e.target.value)} required className="w-full px-3 py-2 rounded-xl border border-slate-200 text-sm focus:outline-none" />
                </div>
                <div>
                  <label className="block text-xs font-bold text-slate-700 mb-1">Syringe Pump Serial ID</label>
                  <input value={formPump} onChange={(e) => setFormPump(e.target.value)} required className="w-full px-3 py-2 rounded-xl border border-slate-200 text-sm font-mono focus:outline-none" />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-bold text-slate-700 mb-1">Patient MRN (Auto-ID)</label>
                  <input value={formMrn} onChange={(e) => setFormMrn(e.target.value)} required className="w-full px-3 py-2 rounded-xl border border-slate-200 text-sm font-mono focus:outline-none bg-slate-50" />
                </div>
                <div>
                  <label className="block text-xs font-bold text-slate-700 mb-1">Patient Full Name</label>
                  <input value={formName} onChange={(e) => setFormName(e.target.value)} required placeholder="e.g. RAGHU" className="w-full px-3 py-2 rounded-xl border border-slate-200 text-sm focus:outline-none" />
                </div>
              </div>

              <div className="grid grid-cols-3 gap-3">
                <div>
                  <label className="block text-xs font-bold text-slate-700 mb-1">Age (Years)</label>
                  <input type="number" value={formAge} onChange={(e) => setFormAge(Number(e.target.value))} required className="w-full px-3 py-2 rounded-xl border border-slate-200 text-sm focus:outline-none" />
                </div>
                <div>
                  <label className="block text-xs font-bold text-slate-700 mb-1">Gender</label>
                  <select value={formGender} onChange={(e) => setFormGender(e.target.value)} className="w-full px-3 py-2 rounded-xl border border-slate-200 text-sm focus:outline-none">
                    <option value="Male">Male</option>
                    <option value="Female">Female</option>
                    <option value="Other">Other</option>
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-bold text-slate-700 mb-1">Blood Group</label>
                  <select value={formBloodGroup} onChange={(e) => setFormBloodGroup(e.target.value)} className="w-full px-3 py-2 rounded-xl border border-slate-200 text-sm font-bold text-rose-600 focus:outline-none">
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
                  <label className="block text-xs font-bold text-slate-700 mb-1">Admission Type</label>
                  <select value={formAdmissionType} onChange={(e) => setFormAdmissionType(e.target.value)} className="w-full px-3 py-2 rounded-xl border border-slate-200 text-sm focus:outline-none">
                    <option value="Emergency">Emergency</option>
                    <option value="Elective / Planned">Elective / Planned</option>
                    <option value="ICU Transfer">ICU Transfer</option>
                    <option value="Trauma / Critical">Trauma / Critical</option>
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-bold text-slate-700 mb-1">Attending Doctor</label>
                  <input value={formDoctor} onChange={(e) => setFormDoctor(e.target.value)} required className="w-full px-3 py-2 rounded-xl border border-slate-200 text-sm focus:outline-none" />
                </div>
              </div>

              <div>
                <label className="block text-xs font-bold text-slate-700 mb-1">Contact Phone Number</label>
                <input value={formPhone} onChange={(e) => setFormPhone(e.target.value)} className="w-full px-3 py-2 rounded-xl border border-slate-200 text-sm focus:outline-none" />
              </div>

              <div>
                <label className="block text-xs font-bold text-slate-700 mb-1">Residential Address</label>
                <input value={formAddress} onChange={(e) => setFormAddress(e.target.value)} className="w-full px-3 py-2 rounded-xl border border-slate-200 text-sm focus:outline-none" />
              </div>

              <button type="submit" className="w-full py-2.5 bg-indigo-600 text-white rounded-xl text-sm font-bold hover:bg-indigo-700 transition mt-2">
                Admit Patient & Bind Syringe Pump
              </button>
            </form>
          </div>
        </div>
      )}

      {/* MODAL: Attach Lab & Diagnostic Reports */}
      {showLabModal && (
        <div className="fixed inset-0 bg-slate-900/60 backdrop-blur-sm flex items-center justify-center p-4 z-50">
          <div className="bg-white rounded-2xl max-w-lg w-full p-6 shadow-2xl border border-slate-100">
            <div className="flex items-center justify-between pb-3 border-b border-slate-100">
              <div className="flex items-center space-x-2">
                <FlaskConical className="w-5 h-5 text-emerald-600" />
                <h3 className="text-base font-bold text-slate-900">Attach Diagnostic / Lab Report</h3>
              </div>
              <button onClick={() => setShowLabModal(false)} className="text-slate-400 hover:text-slate-600"><X className="w-5 h-5" /></button>
            </div>

            <form onSubmit={handleAttachReport} className="mt-4 space-y-4">
              <div>
                <label className="block text-xs font-bold text-slate-700 mb-1">Target Patient MRN</label>
                <input
                  value={labMrn}
                  onChange={(e) => setLabMrn(e.target.value)}
                  placeholder="e.g. PTN-000001"
                  required
                  className="w-full px-3 py-2 rounded-xl border border-slate-200 text-sm font-mono focus:ring-2 focus:ring-emerald-500 focus:outline-none"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-bold text-slate-700 mb-1">Department</label>
                  <select
                    value={labDept}
                    onChange={(e) => {
                      setLabDept(e.target.value);
                      if (e.target.value === 'RADIOLOGY') setLabTestName('Chest X-Ray AP View');
                      else setLabTestName('Complete Blood Count (CBC)');
                    }}
                    className="w-full px-3 py-2 rounded-xl border border-slate-200 text-sm focus:outline-none"
                  >
                    <option value="PATHOLOGY">Pathology (Blood/Urine)</option>
                    <option value="RADIOLOGY">Radiology (X-Ray/Scans)</option>
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-bold text-slate-700 mb-1">Investigation Name</label>
                  <input
                    value={labTestName}
                    onChange={(e) => setLabTestName(e.target.value)}
                    required
                    className="w-full px-3 py-2 rounded-xl border border-slate-200 text-sm focus:outline-none"
                  />
                </div>
              </div>

              {labDept === 'PATHOLOGY' ? (
                <div className="grid grid-cols-3 gap-2 bg-slate-50 p-3 rounded-xl border border-slate-200">
                  <div>
                    <label className="block text-[11px] font-bold text-slate-500">Hb (g/dL)</label>
                    <input value={labHb} onChange={(e) => setLabHb(e.target.value)} className="w-full px-2 py-1 bg-white rounded border text-xs mt-1" />
                  </div>
                  <div>
                    <label className="block text-[11px] font-bold text-slate-500">WBC (/mcL)</label>
                    <input value={labWbc} onChange={(e) => setLabWbc(e.target.value)} className="w-full px-2 py-1 bg-white rounded border text-xs mt-1" />
                  </div>
                  <div>
                    <label className="block text-[11px] font-bold text-slate-500">Platelets</label>
                    <input value={labPlatelets} onChange={(e) => setLabPlatelets(e.target.value)} className="w-full px-2 py-1 bg-white rounded border text-xs mt-1" />
                  </div>
                </div>
              ) : null}

              <div>
                <label className="block text-xs font-bold text-slate-700 mb-1">Technician / Radiologist Observation</label>
                <textarea
                  value={labNotes}
                  onChange={(e) => setLabNotes(e.target.value)}
                  rows={2}
                  placeholder="e.g. Normal blood morphology or Clear lung fields"
                  className="w-full px-3 py-2 rounded-xl border border-slate-200 text-sm focus:outline-none"
                />
              </div>

              <button
                type="submit"
                disabled={labLoading}
                className="w-full py-2.5 bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl text-sm font-bold transition shadow-sm"
              >
                {labLoading ? 'Saving...' : 'Attach Report to Patient'}
              </button>
            </form>
          </div>
        </div>
      )}

      {/* MODAL: Official Print-Ready Patient Clinical Dossier & Discharge Report */}
      {showDossierModal && selectedPatientDossier && (
        <div className="fixed inset-0 bg-slate-900/60 backdrop-blur-sm flex items-center justify-center p-4 z-50">
          <div className="bg-white rounded-2xl max-w-3xl w-full p-8 shadow-2xl border border-slate-100 max-h-[90vh] flex flex-col">
            <div className="flex items-center justify-between pb-4 border-b border-slate-200">
              <div className="flex items-center space-x-3">
                <Building2 className="w-8 h-8 text-indigo-600" />
                <div>
                  <h2 className="text-xl font-black text-slate-900 tracking-tight uppercase">Pulse Hospital & Critical Care Network</h2>
                  <p className="text-xs text-slate-500">Inpatient Clinical Summary & Encounter Audit Dossier</p>
                </div>
              </div>
              <button onClick={() => setShowDossierModal(false)} className="text-slate-400 hover:text-slate-600"><X className="w-6 h-6" /></button>
            </div>

            <div className="mt-4 flex-1 overflow-y-auto space-y-6 text-slate-800 pr-2">
              {/* Section 1: Patient Demographics */}
              <div className="bg-slate-50 p-4 rounded-xl border border-slate-200">
                <h4 className="text-xs font-bold uppercase tracking-wider text-indigo-700 mb-3 flex items-center gap-1.5">
                  <User className="w-4 h-4" /> Patient Demographics & Admission Record
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

              {/* Section 2: Attached Diagnostic Reports */}
              <div>
                <h4 className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-3 flex items-center gap-1.5">
                  <FlaskConical className="w-4 h-4 text-emerald-600" /> Diagnostic Investigations & Pathology / Scan Findings ({selectedPatientDossier.total_reports})
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

              {/* Section 3: Telemetry & Syringe Pump Audit */}
              <div className="bg-indigo-50/60 p-4 rounded-xl border border-indigo-100">
                <h4 className="text-xs font-bold uppercase tracking-wider text-indigo-800 mb-2 flex items-center gap-1.5">
                  <ShieldCheck className="w-4 h-4 text-indigo-600" /> Syringe Pump Infusion & Telemetry Audit
                </h4>
                <div className="grid grid-cols-3 gap-3 text-xs mt-2">
                  <div><span className="text-slate-500 block text-[10px]">Hardware Serial ID</span><span className="font-mono font-bold text-slate-800">{selectedPatientDossier.telemetry_summary?.pump_id}</span></div>
                  <div><span className="text-slate-500 block text-[10px]">Total Medication Delivered</span><span className="font-bold text-indigo-700 text-sm">{selectedPatientDossier.telemetry_summary?.total_volume_ml.toFixed(1)} mL</span></div>
                  <div><span className="text-slate-500 block text-[10px]">Mean Line Pressure</span><span className="font-bold text-slate-800 text-sm">{selectedPatientDossier.telemetry_summary?.avg_pressure_kpa} kPa</span></div>
                </div>
              </div>

              {/* Section 4: Physician Sign-Off */}
              <div className="pt-4 border-t border-slate-200 flex justify-between items-end text-xs text-slate-500">
                <div>
                  <p>Electronically Verified Encounter Record</p>
                  <p className="text-[10px] text-slate-400 font-mono">Doc-UUID: {selectedPatientDossier.admission?.admission_id}</p>
                </div>
                <div className="text-center">
                  <div className="w-40 border-b border-slate-400 mb-1 pb-4 text-slate-400 italic">Clinical Officer Sign</div>
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

      {/* MODAL: Direct Camera & File QR Scanner */}
      {showCameraScanner && (
        <div className="fixed inset-0 bg-slate-900/60 backdrop-blur-sm flex items-center justify-center p-4 z-50">
          <div className="bg-white rounded-2xl max-w-md w-full p-6 shadow-2xl border border-slate-100">
            <div className="flex items-center justify-between pb-3 border-b border-slate-100">
              <div className="flex items-center space-x-2">
                <Camera className="w-5 h-5 text-indigo-600" />
                <h3 className="text-base font-bold text-slate-900">Live Camera QR Scanner</h3>
              </div>
              <button 
                onClick={async () => {
                  if (html5QrCodeRef.current?.isScanning) await html5QrCodeRef.current.stop();
                  setShowCameraScanner(false);
                }} 
                className="text-slate-400 hover:text-slate-600"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            
            <p className="text-xs text-slate-500 mt-2">{scanStatus}</p>

            <div className="mt-4 rounded-xl overflow-hidden border border-slate-200 bg-black min-h-[260px] flex items-center justify-center relative">
              <div id="custom-qr-reader" className="w-full h-full" />
            </div>

            <div className="mt-4 pt-3 border-t border-slate-100 flex items-center justify-between">
              <label className="flex items-center space-x-2 px-3 py-2 bg-slate-50 hover:bg-slate-100 border border-slate-200 rounded-xl cursor-pointer text-xs font-semibold text-slate-700 transition">
                <Upload className="w-4 h-4 text-slate-500" />
                <span>Upload QR Image</span>
                <input type="file" accept="image/*" onChange={handleFileUpload} className="hidden" />
              </label>

              <button 
                onClick={async () => {
                  if (html5QrCodeRef.current?.isScanning) await html5QrCodeRef.current.stop();
                  setShowCameraScanner(false);
                }} 
                className="px-4 py-2 bg-slate-100 text-slate-700 rounded-xl text-xs font-bold hover:bg-slate-200"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      {/* MODAL: Discharged Patients Historical Registry */}
      {showDischargedModal && (
        <div className="fixed inset-0 bg-slate-900/60 backdrop-blur-sm flex items-center justify-center p-4 z-50">
          <div className="bg-white rounded-2xl max-w-4xl w-full p-6 shadow-2xl border border-slate-100 max-h-[90vh] flex flex-col">
            <div className="flex items-center justify-between pb-4 border-b border-slate-100">
              <div className="flex items-center space-x-2">
                <FolderClock className="w-5 h-5 text-amber-600" />
                <div>
                  <h3 className="text-lg font-bold text-slate-900">Discharged Patients Historical Registry</h3>
                  <p className="text-xs text-slate-500">Full audit log of patient admissions, assigned beds, pumps, and total volume delivered.</p>
                </div>
              </div>
              <button onClick={() => setShowDischargedModal(false)} className="text-slate-400 hover:text-slate-600"><X className="w-5 h-5" /></button>
            </div>

            <div className="mt-4 flex-1 overflow-y-auto">
              {dischargedRecords.length === 0 ? (
                <div className="p-8 text-center text-slate-400 text-sm">No discharged patient records found in database.</div>
              ) : (
                <table className="w-full text-left text-xs">
                  <thead className="bg-slate-50 text-slate-500 font-semibold border-b border-slate-200 sticky top-0">
                    <tr>
                      <th className="p-3">Patient MRN & Name</th>
                      <th className="p-3">Bed Station</th>
                      <th className="p-3">Syringe Pump</th>
                      <th className="p-3">Infusion Timeline</th>
                      <th className="p-3">Total Delivered</th>
                      <th className="p-3 text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100 text-slate-700">
                    {dischargedRecords.map((rec) => (
                      <tr key={rec.association_id} className="hover:bg-slate-50">
                        <td className="p-3">
                          <span className="font-bold text-slate-900">{rec.patient_name}</span>
                          <span className="block font-mono text-[11px] text-blue-600">{rec.patient_id}</span>
                        </td>
                        <td className="p-3 font-semibold text-slate-800">{rec.bed_number}</td>
                        <td className="p-3 font-mono text-slate-600">{rec.pump_id}</td>
                        <td className="p-3 text-[11px] text-slate-500">
                          <div>Paired: {rec.paired_at ? new Date(rec.paired_at).toLocaleTimeString() : '--'}</div>
                          <div>Discharged: {rec.discharged_at ? new Date(rec.discharged_at).toLocaleTimeString() : '--'}</div>
                          <div className="font-semibold text-emerald-700">{rec.discharge_type || 'Routine'}</div>
                        </td>
                        <td className="p-3 font-semibold text-slate-800">
                          {rec.total_volume_ml.toFixed(1)} mL
                          <span className="block text-[10px] text-slate-400">Avg Pres: {rec.avg_pressure_kpa} kPa</span>
                        </td>
                        <td className="p-3 text-right space-x-1.5">
                          <button
                            onClick={() => {
                              setShowDischargedModal(false);
                              openDossier(rec.patient_id);
                            }}
                            className="px-2.5 py-1 text-xs font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200 rounded-lg hover:bg-emerald-100"
                          >
                            Dossier
                          </button>
                          <button
                            onClick={() => {
                              setShowDischargedModal(false);
                              openHistoryModal(rec.pump_id);
                            }}
                            className="px-2.5 py-1 text-xs font-semibold bg-indigo-50 text-indigo-700 border border-indigo-200 rounded-lg hover:bg-indigo-100"
                          >
                            Telemetry
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>

            <div className="mt-4 pt-3 border-t border-slate-100 flex justify-end">
              <button
                onClick={() => setShowDischargedModal(false)}
                className="px-4 py-2 bg-slate-100 text-slate-700 rounded-xl text-xs font-bold hover:bg-slate-200"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* MODAL: QR Studio */}
      {showQrStudio && (
        <div className="fixed inset-0 bg-slate-900/60 backdrop-blur-sm flex items-center justify-center p-4 z-50">
          <div className="bg-white rounded-2xl max-w-xl w-full p-6 shadow-2xl border border-slate-100 max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between pb-3 border-b border-slate-100">
              <div className="flex items-center space-x-2">
                <Sparkles className="w-5 h-5 text-violet-600" />
                <h3 className="text-base font-bold text-slate-900">QR Generator & Auto-IDs</h3>
              </div>
              <button onClick={() => setShowQrStudio(false)} className="text-slate-400 hover:text-slate-600"><X className="w-5 h-5" /></button>
            </div>
            
            <p className="text-xs text-slate-500 mt-2">Next available auto-increment IDs for new patient admission and pump pairing.</p>

            <div className="mt-4 grid grid-cols-3 gap-2">
              <div className="p-3 bg-slate-50 rounded-xl border border-slate-200 text-center">
                <span className="text-[10px] font-bold text-slate-400 uppercase">Auto Bed</span>
                <p className="text-sm font-black text-slate-800 mt-0.5">{formBed}</p>
                <button onClick={() => setQrTokenModal({ title: `Bed Tag: ${formBed}`, value: `BED:${formBed}` })} className="mt-2 text-[10px] font-bold text-indigo-600 hover:underline">Get Bed QR</button>
              </div>
              <div className="p-3 bg-slate-50 rounded-xl border border-slate-200 text-center">
                <span className="text-[10px] font-bold text-slate-400 uppercase">Auto Patient</span>
                <p className="text-sm font-black text-slate-800 mt-0.5">{formMrn}</p>
                <button onClick={() => setQrTokenModal({ title: `Patient Wristband: ${formMrn}`, value: `MRN:${formMrn}|NAME:${formName}` })} className="mt-2 text-[10px] font-bold text-indigo-600 hover:underline">Get Patient QR</button>
              </div>
              <div className="p-3 bg-slate-50 rounded-xl border border-slate-200 text-center">
                <span className="text-[10px] font-bold text-slate-400 uppercase">Auto Pump</span>
                <p className="text-sm font-black text-slate-800 mt-0.5">{formPump}</p>
                <button onClick={() => setQrTokenModal({ title: `Pump Chassis: ${formPump}`, value: `PUMP:${formPump}` })} className="mt-2 text-[10px] font-bold text-indigo-600 hover:underline">Get Pump QR</button>
              </div>
            </div>

            <div className="mt-4 flex flex-col items-center justify-center p-4 bg-slate-50 rounded-xl border border-slate-200">
              <span className="text-xs font-bold text-slate-700 mb-2">Composite 3-in-1 Pairing QR Token</span>
              <QRCodeSVG value={generatedCompositeQr} size={160} level="H" />
              <span className="text-[11px] font-mono text-slate-500 mt-2 break-all text-center">{generatedCompositeQr}</span>
            </div>

            <div className="mt-4 flex gap-2">
              <button
                onClick={() => {
                  setShowQrStudio(false);
                  setShowPairModal(true);
                }}
                className="flex-1 py-2.5 bg-violet-600 text-white rounded-xl text-xs font-bold hover:bg-violet-700"
              >
                Direct Pair Using Current Suggested IDs
              </button>
              <button
                onClick={() => setShowQrStudio(false)}
                className="px-4 py-2.5 bg-slate-100 text-slate-700 rounded-xl text-xs font-bold hover:bg-slate-200"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* MODAL: Single QR Code View */}
      {qrTokenModal && (
        <div className="fixed inset-0 bg-slate-900/60 backdrop-blur-sm flex items-center justify-center p-4 z-50">
          <div className="bg-white rounded-2xl max-w-xs w-full p-6 text-center shadow-2xl border border-slate-100">
            <h3 className="text-sm font-bold text-slate-900">{qrTokenModal.title}</h3>
            <div className="mt-4 flex justify-center p-4 bg-slate-50 rounded-xl border border-slate-200">
              <QRCodeSVG value={qrTokenModal.value} size={160} level="H" />
            </div>
            <p className="text-[11px] text-slate-400 mt-3 font-mono break-all">{qrTokenModal.value}</p>
            <button onClick={() => setQrTokenModal(null)} className="mt-4 w-full py-2 bg-slate-100 text-slate-700 rounded-xl text-xs font-bold hover:bg-slate-200">
              Done
            </button>
          </div>
        </div>
      )}

      {/* MODAL: Historical Infusion & Pressure Curves */}
      {selectedHistoryPump && (
        <div className="fixed inset-0 bg-slate-900/60 backdrop-blur-sm flex items-center justify-center p-4 z-50">
          <div className="bg-white rounded-2xl max-w-2xl w-full p-6 shadow-2xl border border-slate-100">
            <div className="flex items-center justify-between pb-3 border-b border-slate-100">
              <div>
                <h3 className="text-base font-bold text-slate-900">TimescaleDB Historical Telemetry</h3>
                <p className="text-xs text-slate-500 font-mono">Pump: {selectedHistoryPump}</p>
              </div>
              <button onClick={() => setSelectedHistoryPump(null)} className="text-slate-400 hover:text-slate-600"><X className="w-5 h-5" /></button>
            </div>
            <div className="h-64 mt-4">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={historyLogs}>
                  <defs>
                    <linearGradient id="colorPressure" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#ef4444" stopOpacity={0.4}/>
                      <stop offset="95%" stopColor="#ef4444" stopOpacity={0}/>
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
                  <XAxis dataKey="time" tick={{ fontSize: 10 }} />
                  <YAxis unit=" kPa" tick={{ fontSize: 10 }} domain={[0, 140]} />
                  <Tooltip />
                  <Area type="monotone" dataKey="pressure" stroke="#ef4444" strokeWidth={2} fillOpacity={1} fill="url(#colorPressure)" name="Line Pressure (kPa)" />
                </AreaChart>
              </ResponsiveContainer>
            </div>
            <div className="mt-4 flex justify-end">
              <button onClick={() => setSelectedHistoryPump(null)} className="px-4 py-2 bg-slate-100 text-slate-700 rounded-xl text-xs font-bold hover:bg-slate-200">
                Done
              </button>
            </div>
          </div>
        </div>
      )}
    </main>
  );
}
