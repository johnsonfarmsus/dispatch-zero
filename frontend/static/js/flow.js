// In-flight mission helpers: cache, GPS watch, geo math.

import { api } from "./api.js";

let _cached = null;       // { id, mission_data, fetched_at }
let _watchId = null;
let _lastFix = null;      // { lat, lng, accuracy_m, ts }
const _fixListeners = new Set();
let _lastDebrief = null;  // populated by Capture, consumed by Debrief

export async function loadMission(id) {
  if (_cached?.id === id && (Date.now() - _cached.fetched_at) < 60000) {
    return _cached.mission_data;
  }
  const r = await api.get(`/missions/${id}`);
  if (!r.ok) {
    const e = new Error(r.data?.detail || "Mission not found");
    e.status = r.status;
    throw e;
  }
  _cached = { id, mission_data: r.data, fetched_at: Date.now() };
  return r.data;
}

export function clearMissionCache() {
  _cached = null;
}

export function setLastDebrief(d) { _lastDebrief = d; }
export function getLastDebrief() { return _lastDebrief; }
export function clearLastDebrief() { _lastDebrief = null; }

export function startWatchingPosition() {
  if (_watchId !== null || !navigator.geolocation) return;
  _watchId = navigator.geolocation.watchPosition(
    (pos) => {
      _lastFix = {
        lat: pos.coords.latitude,
        lng: pos.coords.longitude,
        accuracy_m: pos.coords.accuracy,
        ts: Date.now(),
      };
      for (const fn of _fixListeners) fn(_lastFix);
    },
    () => { /* fail silent — UI shows no-fix state */ },
    { enableHighAccuracy: true, maximumAge: 5000, timeout: 30000 },
  );
}

export function stopWatchingPosition() {
  if (_watchId !== null) {
    navigator.geolocation.clearWatch(_watchId);
    _watchId = null;
  }
}

export function getLastFix() { return _lastFix; }

export function onFix(fn) {
  _fixListeners.add(fn);
  return () => _fixListeners.delete(fn);
}

export async function getFreshFix({
  maxAgeMs = 5000,
  enableHighAccuracy = true,
  timeoutMs = 15000,
} = {}) {
  if (_lastFix && (Date.now() - _lastFix.ts) < maxAgeMs) return _lastFix;
  return new Promise((resolve, reject) => {
    if (!navigator.geolocation) {
      reject(new Error("geolocation unsupported"));
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const fix = {
          lat: pos.coords.latitude,
          lng: pos.coords.longitude,
          accuracy_m: pos.coords.accuracy,
          ts: Date.now(),
        };
        _lastFix = fix;
        resolve(fix);
      },
      (err) => reject(err),
      { enableHighAccuracy, timeout: timeoutMs, maximumAge: 0 },
    );
  });
}

// ----- Geo math -----
const R_EARTH_M = 6_371_000;

export function distanceM(lat1, lng1, lat2, lng2) {
  const phi1 = lat1 * Math.PI / 180;
  const phi2 = lat2 * Math.PI / 180;
  const dPhi = (lat2 - lat1) * Math.PI / 180;
  const dLam = (lng2 - lng1) * Math.PI / 180;
  const a = Math.sin(dPhi / 2) ** 2 + Math.cos(phi1) * Math.cos(phi2) * Math.sin(dLam / 2) ** 2;
  return 2 * R_EARTH_M * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

export function bearingDeg(lat1, lng1, lat2, lng2) {
  const phi1 = lat1 * Math.PI / 180;
  const phi2 = lat2 * Math.PI / 180;
  const dLam = (lng2 - lng1) * Math.PI / 180;
  const y = Math.sin(dLam) * Math.cos(phi2);
  const x = Math.cos(phi1) * Math.sin(phi2) - Math.sin(phi1) * Math.cos(phi2) * Math.cos(dLam);
  return ((Math.atan2(y, x) * 180 / Math.PI) + 360) % 360;
}

export function bearingCompassLabel(deg) {
  // Convert 0-360 → "N42E" style label
  const dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"];
  const idx = Math.round(deg / 45) % 8;
  return dirs[idx];
}

export function formatDistance(m) {
  if (m == null || isNaN(m)) return "—";
  if (m < 1000) return `${Math.round(m)}m`;
  return `${(m / 1000).toFixed(2)}km`;
}
