/**
 * app.js — MusicMap
 *
 * Flow:
 *   1. User taps ▶ → request geolocation permission
 *   2. Open WebSocket to /ws/audio → receive raw PCM, play via AudioContext
 *   3. Every LOCATE_INTERVAL_MS → POST /locate with current lat/lng
 *   4. Server reverse-geocodes → steers Lyria → returns zone info
 *   5. Paint a colored circle on the map, update now-playing card
 */

const BACKEND = `${location.protocol}//${location.hostname}:8000`;
const HISTORY_MAX = 80;   // max zone circles kept on map

let LOCATE_INTERVAL_MS = 5_000;

// ── DOM refs ──────────────────────────────────────────────────────────────────
const btnPlay     = document.getElementById('btn-play');
const statusDot   = document.getElementById('status-dot');
const errorToast  = document.getElementById('error-toast');
const npPlace     = document.getElementById('np-place');
const npMood      = document.getElementById('np-mood');
const npGenre     = document.getElementById('np-genre');
const npBpm       = document.getElementById('np-bpm');
const zoneBar     = document.getElementById('zone-color-bar');
const waveformEl  = document.getElementById('waveform');

// ── State ─────────────────────────────────────────────────────────────────────
let running      = false;
let locateTimer  = null;
let audioCtx     = null;
let audioWs      = null;
let analyserNode = null;
let waveformRaf  = null;
let leafletMap   = null;
let playerMarker = null;
const zoneCircles = [];   // { lat, lon, color } — kept for replay

// ── Map init ──────────────────────────────────────────────────────────────────

function initMap(lat, lon) {
  if (leafletMap) return;

  leafletMap = L.map('map', { zoomControl: true, attributionControl: true })
    .setView([lat, lon], 17);

  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    maxZoom: 19,
  }).addTo(leafletMap);

  // Player dot
  const playerIcon = L.divIcon({
    className: '',
    html: `<div style="
      width:16px;height:16px;border-radius:50%;
      background:#7c6af7;
      border:3px solid #fff;
      box-shadow:0 0 12px rgba(124,106,247,0.8);
    "></div>`,
    iconSize: [16, 16],
    iconAnchor: [8, 8],
  });

  playerMarker = L.marker([lat, lon], { icon: playerIcon, zIndexOffset: 1000 })
    .addTo(leafletMap);
}

function updatePlayerPosition(lat, lon) {
  if (!leafletMap || !playerMarker) return;
  playerMarker.setLatLng([lat, lon]);
  leafletMap.panTo([lat, lon], { animate: true, duration: 0.8 });
}

function paintZone(lat, lon, color) {
  if (!leafletMap) return;

  // Fade older circles
  if (zoneCircles.length >= HISTORY_MAX) {
    const oldest = zoneCircles.shift();
    if (oldest.circle) leafletMap.removeLayer(oldest.circle);
  }

  const circle = L.circle([lat, lon], {
    radius: 30,
    color: color,
    fillColor: color,
    fillOpacity: 0.35,
    weight: 0,
  }).addTo(leafletMap);

  zoneCircles.push({ lat, lon, color, circle });
}

// ── Audio PCM playback ────────────────────────────────────────────────────────

function initAudio() {
  audioCtx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 48_000 });

  analyserNode = audioCtx.createAnalyser();
  analyserNode.fftSize = 256;
  analyserNode.connect(audioCtx.destination);

  const wsUrl = `${BACKEND.replace('http', 'ws')}/ws/audio`;
  audioWs = new WebSocket(wsUrl);
  audioWs.binaryType = 'arraybuffer';

  audioWs.addEventListener('message', (evt) => playPcmChunk(evt.data));
  audioWs.addEventListener('close',   () => { if (running) showError('Audio disconnected — tap play to reconnect.'); });
}

function playPcmChunk(arrayBuffer) {
  const samples   = new Int16Array(arrayBuffer);
  const numFrames = Math.floor(samples.length / 2);
  const buf       = audioCtx.createBuffer(2, numFrames, 48_000);
  const left      = buf.getChannelData(0);
  const right     = buf.getChannelData(1);

  for (let i = 0; i < numFrames; i++) {
    left[i]  = samples[i * 2]     / 32768;
    right[i] = samples[i * 2 + 1] / 32768;
  }

  const src = audioCtx.createBufferSource();
  src.buffer = buf;
  src.connect(analyserNode);

  const startAt = Math.max(audioCtx.currentTime, window._nextAudioTime ?? 0);
  src.start(startAt);
  window._nextAudioTime = startAt + buf.duration;
}

// ── Waveform ──────────────────────────────────────────────────────────────────

function drawWaveform() {
  if (!analyserNode) return;

  const ctx  = waveformEl.getContext('2d');
  const W    = waveformEl.width  = waveformEl.offsetWidth;
  const H    = waveformEl.height = waveformEl.offsetHeight;
  const data = new Uint8Array(analyserNode.fftSize);
  analyserNode.getByteTimeDomainData(data);

  ctx.clearRect(0, 0, W, H);
  ctx.strokeStyle = '#7c6af7';
  ctx.lineWidth   = 1.5;
  ctx.beginPath();

  const step = W / data.length;
  for (let i = 0; i < data.length; i++) {
    const x = i * step;
    const y = (data[i] / 255) * H;
    i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
  }
  ctx.stroke();

  waveformRaf = requestAnimationFrame(drawWaveform);
}

// ── Location + scene ──────────────────────────────────────────────────────────

function getCurrentPosition() {
  return new Promise((resolve, reject) =>
    navigator.geolocation.getCurrentPosition(resolve, reject, {
      enableHighAccuracy: true,
      timeout: 8_000,
      maximumAge: 3_000,
    })
  );
}

async function locateAndUpdate() {
  let position;
  try {
    position = await getCurrentPosition();
  } catch (err) {
    showError(`GPS error: ${err.message}`);
    return;
  }

  const { latitude: lat, longitude: lon } = position.coords;
  updatePlayerPosition(lat, lon);
  setStatus('loading');

  try {
    const res = await fetch(`${BACKEND}/locate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ lat, lon }),
    });
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();

    updateNowPlaying(data);
    paintZone(lat, lon, data.zone_color);
    hideError();
    setStatus('active');
  } catch (err) {
    showError(`Location error: ${err.message}`);
    setStatus('active');
  }
}

// ── UI ────────────────────────────────────────────────────────────────────────

function updateNowPlaying(data) {
  const { scene, zone_color, display_name } = data;

  zoneBar.style.background = zone_color;

  npPlace.style.opacity = '0';
  setTimeout(() => {
    npPlace.textContent  = display_name || scene.setting;
    npPlace.style.opacity = '1';
  }, 150);

  npMood.textContent  = scene.mood;
  npGenre.textContent = scene.suggested_genre;
  npBpm.textContent   = `${scene.suggested_bpm} BPM`;
  npMood.style.background = zone_color;
}

function setStatus(state) {
  statusDot.className = state === 'active' ? 'dot-active'
    : state === 'loading' ? 'dot-loading'
    : 'dot-idle';
}

function showError(msg) {
  errorToast.textContent = msg;
  errorToast.hidden = false;
}

function hideError() {
  errorToast.hidden = true;
}

// ── Start / stop ──────────────────────────────────────────────────────────────

async function loadConfig() {
  try {
    const res = await fetch(`${BACKEND}/config`);
    if (res.ok) {
      const cfg = await res.json();
      LOCATE_INTERVAL_MS = cfg.locate_interval_ms ?? LOCATE_INTERVAL_MS;
    }
  } catch { /* keep defaults */ }
}

async function startSession() {
  btnPlay.disabled = true;

  await loadConfig();

  // Get initial position to center the map
  let position;
  try {
    position = await getCurrentPosition();
  } catch {
    showError('Location permission denied. Please allow location access.');
    btnPlay.disabled = false;
    return;
  }

  const { latitude: lat, longitude: lon } = position.coords;
  initMap(lat, lon);
  initAudio();

  running = true;
  btnPlay.textContent = '⏹';
  btnPlay.classList.add('playing');
  btnPlay.disabled = false;
  setStatus('active');

  await locateAndUpdate();
  locateTimer = setInterval(locateAndUpdate, LOCATE_INTERVAL_MS);
  drawWaveform();
}

function stopSession() {
  running = false;
  clearInterval(locateTimer);
  cancelAnimationFrame(waveformRaf);

  if (audioWs)  { audioWs.close();  audioWs  = null; }
  if (audioCtx) { audioCtx.close(); audioCtx = null; }

  btnPlay.textContent = '▶';
  btnPlay.classList.remove('playing');
  setStatus('idle');
}

// ── Button ────────────────────────────────────────────────────────────────────

btnPlay.addEventListener('click', () => {
  if (running) stopSession();
  else         startSession();
});
