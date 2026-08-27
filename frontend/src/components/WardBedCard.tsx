import React from 'react';
import { AlertTriangle, Wifi, Activity } from 'lucide-react';

export interface BedPumpCardProps {
  bedNumber: string;
  patientName: string;
  patientMrn: string;
  diagnosis: string;
  pumpId: string;
  drugName: string;
  rateMlHr: number;
  deliveredMl: number;
  vtbiMl: number;
  timeRemainingSec: number;
  pressureKpa: number;
  alarms: string[];
  isOnline: boolean;
}

export const WardBedCard: React.FC<BedPumpCardProps> = ({
  bedNumber, patientName, patientMrn, diagnosis, pumpId,
  drugName, rateMlHr, deliveredMl, vtbiMl, timeRemainingSec, pressureKpa, alarms, isOnline
}) => {
  const hasCriticalAlarm = alarms.length > 0;
  const progressPct = Math.min(100, Math.round((deliveredMl / (vtbiMl || 1)) * 100));

  const formatTime = (secs: number) => {
    const hrs = Math.floor(secs / 3600);
    const mins = Math.floor((secs % 3600) / 60);
    return `${hrs}h ${mins}m left`;
  };

  return (
    <div className={`rounded-xl border p-5 shadow-sm transition-all duration-200 bg-white ${
      hasCriticalAlarm ? 'border-red-500 ring-2 ring-red-400 bg-red-50/10' : 'border-slate-200 hover:shadow-md'
    }`}>
      <div className="flex items-center justify-between border-b border-slate-100 pb-3">
        <div className="flex items-center space-x-2">
          <span className="text-xl font-black text-slate-800 tracking-tight">{bedNumber}</span>
          <span className="text-xs font-semibold px-2 py-0.5 rounded bg-blue-50 text-blue-700 border border-blue-100">
            {patientMrn}
          </span>
        </div>
        <div className="flex items-center space-x-2">
          <Wifi className={`w-4 h-4 ${isOnline ? 'text-emerald-500' : 'text-slate-300 animate-pulse'}`} />
          <span className="text-xs font-mono text-slate-500 font-medium">{pumpId}</span>
        </div>
      </div>

      <div className="mt-3 space-y-0.5">
        <p className="text-sm font-bold text-slate-900">{patientName}</p>
        <p className="text-xs text-slate-500 truncate">{diagnosis}</p>
      </div>

      <div className="mt-4 bg-slate-50 border border-slate-100 rounded-lg p-3">
        <div className="flex justify-between items-baseline">
          <div>
            <span className="text-xs font-bold uppercase tracking-wider text-indigo-700">{drugName}</span>
            <div className="text-[11px] text-slate-500 font-mono mt-0.5">Line Pressure: {pressureKpa} kPa</div>
          </div>
          <div className="text-right">
            <span className="text-base font-black text-slate-800 font-mono">{rateMlHr.toFixed(1)}</span>
            <span className="text-xs text-slate-500 ml-1">mL/h</span>
          </div>
        </div>
        
        <div className="w-full bg-slate-200 rounded-full h-2 mt-3 overflow-hidden">
          <div 
            className={`h-2 rounded-full transition-all duration-500 ${hasCriticalAlarm ? 'bg-red-500' : 'bg-blue-600'}`} 
            style={{ width: `${progressPct}%` }}
          />
        </div>

        <div className="flex justify-between text-[11px] text-slate-500 mt-2 font-mono">
          <span>{deliveredMl.toFixed(1)} / {vtbiMl.toFixed(1)} mL ({progressPct}%)</span>
          <span>{formatTime(timeRemainingSec)}</span>
        </div>
      </div>

      {hasCriticalAlarm ? (
        <div className="mt-3 flex items-center space-x-1.5 text-xs text-red-600 font-bold animate-pulse bg-red-50 p-2 rounded border border-red-200">
          <AlertTriangle className="w-4 h-4 flex-shrink-0" />
          <span>{alarms.join(', ')}</span>
        </div>
      ) : (
        <div className="mt-3 flex items-center space-x-1 text-[11px] text-emerald-600 font-medium">
          <Activity className="w-3.5 h-3.5" />
          <span>Normal Delivery Profile</span>
        </div>
      )}
    </div>
  );
};