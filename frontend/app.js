/**
 * app.js — Seenic
 *
 * Two modes:
 *   Passive  — GPS polls /locate every LOCATE_INTERVAL_MS → Lyria steered by place type
 *   Active   — User taps 📷 → camera frame → POST /scan → Lyria steered by Gemini vision + pin dropped
 *
 * Audio: PCM chunks from /ws/audio decoded and fed into an AudioWorklet ring buffer.
 * Map:   Google Maps JavaScript API (key loaded from /config).
 */

const BACKEND = `${location.protocol}//${location.hostname}:8000`;
let LOCATE_INTERVAL_MS = 5_000;

// ── DOM refs ──────────────────────────────────────────────────────────────────
const btnPlay    = document.getElementById('btn-play');
const btnScan    = document.getElementById('btn-scan');
const statusDot  = document.getElementById('status-dot');
const errorToast = document.getElementById('error-toast');
const npPlace    = document.getElementById('np-place');
const npMood     = document.getElementById('np-mood');
const npGenre    = document.getElementById('np-genre');
const npBpm      = document.getElementById('np-bpm');
const zoneBar    = document.getElementById('zone-color-bar');
const waveformEl = document.getElementById('waveform');
const scanOverlay   = document.getElementById('scan-overlay');
const scanVideoEl   = document.getElementById('scan-preview');
const snapshotCanvas = document.getElementById('snapshot');

// ── State ─────────────────────────────────────────────────────────────────────
let running      = false;
let scanning     = false;
let locateTimer  = null;
let audioCtx     = null;
let audioWs      = null;
let workletNode  = null;
let analyserNode = null;
let waveformRaf  = null;
let gmap         = null;
let playerMarker = null;
const zoneCircles = [];
const pinMarkers  = [];

// ── Google Maps ───────────────────────────────────────────────────────────────

// Schematic sage-green map — matches reference device aesthetic
const DARK_MAP_STYLE = [
  { elementType: 'geometry',                 stylers: [{ color: '#bdd4b2' }] },
  { elementType: 'labels.text.fill',         stylers: [{ color: '#1e2e1e' }] },
  { elementType: 'labels.text.stroke',       stylers: [{ color: '#bdd4b2' }] },
  { featureType: 'road',       elementType: 'geometry',        stylers: [{ color: '#8aaa78' }] },
  { featureType: 'road',       elementType: 'geometry.stroke', stylers: [{ color: '#a0ba8e' }] },
  { featureType: 'road.highway',  elementType: 'geometry',     stylers: [{ color: '#5a7a48' }] },
  { featureType: 'road.highway',  elementType: 'geometry.stroke', stylers: [{ color: '#6a8a58' }] },
  { featureType: 'road.local', elementType: 'labels',          stylers: [{ visibility: 'off' }] },
  { featureType: 'water',      elementType: 'geometry',        stylers: [{ color: '#8ab4ac' }] },
  { featureType: 'water',      elementType: 'labels.text.fill', stylers: [{ color: '#3a5a54' }] },
  { featureType: 'poi',        elementType: 'geometry',        stylers: [{ color: '#aac89a' }] },
  { featureType: 'poi.park',   elementType: 'geometry',        stylers: [{ color: '#a0c890' }] },
  { featureType: 'transit',    elementType: 'geometry',        stylers: [{ color: '#b4cca4' }] },
  { featureType: 'administrative', elementType: 'geometry.stroke', stylers: [{ color: '#7a9a6a' }] },
  { featureType: 'administrative.locality', elementType: 'labels.text.fill', stylers: [{ color: '#1e2e1e' }] },
];

function initMap(lat, lon) {
  if (gmap) return;

  gmap = new google.maps.Map(document.getElementById('map'), {
    center: { lat, lng: lon },
    zoom: 17,
    mapTypeId: 'roadmap',
    disableDefaultUI: true,
    styles: DARK_MAP_STYLE,
  });

  const playerIcon = {
    path: google.maps.SymbolPath.CIRCLE,
    scale: 7,
    fillColor: '#3a5a3a',
    fillOpacity: 1,
    strokeColor: '#ffffff',
    strokeWeight: 2,
  };

  playerMarker = new google.maps.Marker({
    position: { lat, lng: lon },
    map: gmap,
    icon: playerIcon,
    zIndex: 999,
  });
}

function updatePlayerPosition(lat, lon) {
  if (!gmap || !playerMarker) return;
  const pos = { lat, lng: lon };
  playerMarker.setPosition(pos);
  gmap.panTo(pos);
}

function paintZone(lat, lon, color) {
  if (!gmap) return;

  if (zoneCircles.length >= 80) {
    zoneCircles.shift().setMap(null);
  }

  const circle = new google.maps.Circle({
    center: { lat, lng: lon },
    radius: 25,
    fillColor: color,
    fillOpacity: 0.35,
    strokeWeight: 0,
    map: gmap,
  });

  zoneCircles.push(circle);
}

function paintScanPin(pin) {
  if (!gmap) return;  

  const marker = new google.maps.Marker({
    position: { lat: pin.lat, lng: pin.lon },
    map: gmap,
    title: `${pin.display_name}\n${pin.genre} · ${pin.bpm} BPM`,
    icon: {
      path: google.maps.SymbolPath.BACKWARD_CLOSED_ARROW,
      scale: 5,
      fillColor: '#33ff33',
      fillOpacity: 0.8,
      strokeColor: '#030c03',
      strokeWeight: 2,
    },
    zIndex: 100,
  });

  const infoWindow = new google.maps.InfoWindow({
    content: `<div style="color:#0d0d12;font-family:sans-serif;font-size:13px;padding:4px 2px">
      <strong>${pin.display_name}</strong><br>
      ${pin.scene_description}<br>
      <span style="color:#555">${pin.genre} · ${pin.bpm} BPM</span>
    </div>`,
  });

  marker.addListener('click', () => infoWindow.open(gmap, marker));
  pinMarkers.push(marker);
}

async function loadExistingPins() {
  try {
    const res = await fetch(`${BACKEND}/pins`);
    if (!res.ok) return;
    const { pins } = await res.json();
    pins.forEach(paintScanPin);
  } catch { /* non-fatal */ }
}

// ── Audio ─────────────────────────────────────────────────────────────────────

async function initAudio() {
  audioCtx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 48_000 });

  await audioCtx.audioWorklet.addModule('/audio-processor.js');
  workletNode = new AudioWorkletNode(audioCtx, 'seenic-audio', { outputChannelCount: [2] });

  analyserNode = audioCtx.createAnalyser();
  analyserNode.fftSize = 256;

  workletNode.connect(analyserNode);
  analyserNode.connect(audioCtx.destination);

  const wsUrl = `${BACKEND.replace('http', 'ws')}/ws/audio`;
  audioWs = new WebSocket(wsUrl);
  audioWs.binaryType = 'arraybuffer';

  audioWs.addEventListener('message', ({ data }) => {
    // Decode Int16 interleaved stereo → Float32 interleaved, send to worklet
    const int16  = new Int16Array(data);
    const float32 = new Float32Array(int16.length);
    for (let i = 0; i < int16.length; i++) {
      float32[i] = int16[i] / 32768;
    }
    workletNode.port.postMessage(float32, [float32.buffer]);
  });

  audioWs.addEventListener('close', () => {
    if (running) showError('Audio disconnected — tap ▶ to reconnect.');
  });
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
  ctx.strokeStyle = '#33ff33';
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

// ── Geolocation ───────────────────────────────────────────────────────────────

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
    showError(`GPS: ${err.message}`);
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
  } catch (err) {
    showError(`Locate: ${err.message}`);
  } finally {
    setStatus('active');
  }
}

// ── Camera scan ───────────────────────────────────────────────────────────────

/**
 * Capture a compressed JPEG from the video element.
 * Scales down to 800×600 max and uses quality 0.6 to keep upload small (~80 KB).
 */
function captureFrame(video) {
  const MAX_W = 800, MAX_H = 600;
  const scale = Math.min(MAX_W / video.videoWidth, MAX_H / video.videoHeight, 1);
  const w = Math.round(video.videoWidth  * scale);
  const h = Math.round(video.videoHeight * scale);
  snapshotCanvas.width  = w;
  snapshotCanvas.height = h;
  snapshotCanvas.getContext('2d').drawImage(video, 0, 0, w, h);
  return new Promise(resolve => snapshotCanvas.toBlob(resolve, 'image/jpeg', 0.6));
}

async function doScan() {
  if (scanning) return;
  scanning = true;
  btnScan.disabled = true;

  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: 'environment' },
      audio: false,
    });
  } catch (err) {
    showError(`Camera: ${err.message}`);
    scanning = false;
    btnScan.disabled = false;
    return;
  }

  scanVideoEl.srcObject = stream;
  scanOverlay.hidden = false;

  // Give the camera 1.5 s to stabilize, then capture
  await new Promise(r => setTimeout(r, 1500));

  let blob;
  try {
    blob = await captureFrame(scanVideoEl);
  } catch {
    showError('Could not capture frame.');
    stream.getTracks().forEach(t => t.stop());
    scanOverlay.hidden = true;
    scanning = false;
    btnScan.disabled = false;
    return;
  }

  // Stop camera immediately after capture
  stream.getTracks().forEach(t => t.stop());

  let position;
  try {
    position = await getCurrentPosition();
  } catch (err) {
    showError(`GPS during scan: ${err.message}`);
    scanOverlay.hidden = true;
    scanning = false;
    btnScan.disabled = false;
    return;
  }

  const { latitude: lat, longitude: lon } = position.coords;
  const form = new FormData();
  form.append('file', blob, 'scan.jpg');
  form.append('lat', lat);
  form.append('lon', lon);

  try {
    const res = await fetch(`${BACKEND}/scan`, { method: 'POST', body: form });
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    updateNowPlaying({
      scene: data.scene,
      zone_color: data.pin.zone_color,
      display_name: data.pin.display_name,
    });
    paintScanPin(data.pin);
    hideError();
  } catch (err) {
    showError(`Scan failed: ${err.message}`);
  } finally {
    scanOverlay.hidden = true;
    scanning = false;
    btnScan.disabled = false;
  }
}

// ── Pixel album art ───────────────────────────────────────────────────────────

function drawAlbumArt(zoneColor) {
  const canvas = document.getElementById('album-art');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const W = canvas.width, H = canvas.height;
  const cols = 7, rows = 7;
  const cw = Math.floor(W / cols), ch = Math.floor(H / rows);

  // Seed from zone color hex → symmetrical identicon pattern
  const seed = parseInt((zoneColor || '#1aaa1a').replace('#', ''), 16);

  ctx.fillStyle = '#010601';
  ctx.fillRect(0, 0, W, H);

  ctx.fillStyle = '#33ff33';
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < Math.ceil(cols / 2); c++) {
      if ((seed >> (r * 4 + c)) & 1) {
        ctx.fillRect(c * cw + 1,           r * ch + 1, cw - 2, ch - 2);
        ctx.fillRect((cols - 1 - c) * cw + 1, r * ch + 1, cw - 2, ch - 2);
      }
    }
  }
}

// ── UI ────────────────────────────────────────────────────────────────────────

function updateNowPlaying({ scene, zone_color, display_name }) {
  zoneBar.style.background = zone_color;
  drawAlbumArt(zone_color);

  npPlace.style.opacity = '0';
  setTimeout(() => {
    npPlace.textContent   = display_name || scene.setting;
    npPlace.style.opacity = '1';
  }, 150);

  npMood.textContent  = scene.mood;
  npGenre.textContent = scene.suggested_genre;
  npBpm.textContent   = `${scene.suggested_bpm} BPM`;
  npMood.style.background = zone_color;
}

function setStatus(state) {
  statusDot.className =
    state === 'active'  ? 'dot-active'  :
    state === 'loading' ? 'dot-loading' :
    'dot-idle';
}

function showError(msg) {
  errorToast.textContent = msg;
  errorToast.hidden = false;
}

function hideError() {
  errorToast.hidden = true;
}

// ── Session lifecycle ─────────────────────────────────────────────────────────

async function loadConfig() {
  try {
    const res = await fetch(`${BACKEND}/config`);
    if (!res.ok) return {};
    return await res.json();
  } catch {
    return {};
  }
}

function loadGoogleMaps(apiKey) {
  return new Promise((resolve, reject) => {
    if (window.google?.maps) { resolve(); return; }
    window._mapsReady = resolve;
    const script = document.createElement('script');
    script.src = `https://maps.googleapis.com/maps/api/js?key=${apiKey}&callback=_mapsReady`;
    script.onerror = reject;
    document.head.appendChild(script);
  });
}

async function startSession() {
  btnPlay.disabled = true;

  const cfg = await loadConfig();
  LOCATE_INTERVAL_MS = cfg.locate_interval_ms ?? LOCATE_INTERVAL_MS;
  const mapsKey = cfg.maps_api_key || '';

  // Get location first (needed to center map)
  let position;
  try {
    position = await getCurrentPosition();
  } catch {
    showError('Location permission denied. Please allow location access and refresh.');
    btnPlay.disabled = false;
    return;
  }

  const { latitude: lat, longitude: lon } = position.coords;

  // Load Google Maps SDK
  try {
    await loadGoogleMaps(mapsKey);
  } catch {
    showError('Google Maps failed to load. Check your API key.');
    btnPlay.disabled = false;
    return;
  }

  initMap(lat, lon);

  // Init audio (requires secure context — use ngrok on physical phone)
  try {
    await initAudio();
  } catch (err) {
    showError(`Audio init failed: ${err.message}. Are you on HTTPS?`);
    btnPlay.disabled = false;
    return;
  }

  running = true;
  btnPlay.textContent = '⏹';
  btnPlay.classList.add('playing');
  btnPlay.disabled = false;
  btnScan.hidden = false;
  setStatus('active');

  await locateAndUpdate();
  await loadExistingPins();
  locateTimer = setInterval(locateAndUpdate, LOCATE_INTERVAL_MS);
  drawWaveform();
}

function stopSession() {
  running = false;
  clearInterval(locateTimer);
  cancelAnimationFrame(waveformRaf);

  if (audioWs)  { audioWs.close();  audioWs  = null; }
  if (audioCtx) { audioCtx.close(); audioCtx = null; }
  workletNode = null;

  btnPlay.textContent = '▶II';
  btnPlay.classList.remove('playing');
  btnScan.hidden = true;
  setStatus('idle');
}

// ── Event listeners ───────────────────────────────────────────────────────────

btnPlay.addEventListener('click', () => {
  if (running) stopSession();
  else         startSession();
});

btnScan.addEventListener('click', doScan);
