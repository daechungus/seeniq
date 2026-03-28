# Seenic — The World Has a Soundtrack

> Built for the Google Gemini UCLA Hackathon 2026

Seenic is a crowdsourced music map. Walk anywhere and AI composes music that matches your surroundings in real time. Scan your environment to pin that soundtrack to the map — anyone who walks into your zone later hears what you heard.

---

## How It Works

**Passive mode** — GPS polls your location every 5 seconds. The backend reverse-geocodes your coordinates and maps the place type (park, café, nightclub, library, etc.) to a music scene. Lyria 3 generates a matching audio clip that loops until the scene changes.

**Active scan** — Tap SCAN. Your camera captures a frame. Gemini Vision analyzes the scene and returns a structured description: mood, energy, BPM, genre. Lyria immediately generates music for that exact moment. A pin is dropped on the map with a 30-meter influence radius.

**Location memory** — Scanned pins persist for 15 minutes. Anyone who walks within 30m of your pin hears your soundtrack. A pulsing ZONE badge appears on their player when they're inside someone else's zone. Pins are shared server-side across all connected users.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | Vanilla HTML / JS / CSS, Google Maps JavaScript API |
| Backend | Python FastAPI + uvicorn |
| Vision AI | Gemini 2.5 Flash Lite — scene analysis from camera frames |
| Music AI | Lyria 3 Clip Preview — generates ~47s MP3 clips from text prompts |
| Geocoding | Nominatim (OpenStreetMap) — free, no key required |
| Maps | Google Maps JavaScript API |

---

## Setup

### Prerequisites
- Anaconda (base environment)
- API keys: `GEMINI_API_KEY`, `GOOGLE_MAPS_API_KEY`

### Install dependencies
```bash
conda activate base
pip install fastapi uvicorn python-dotenv httpx google-genai pillow
```

### Configure API keys
Create `backend/.env`:
```
GEMINI_API_KEY=your_key_here
GOOGLE_MAPS_API_KEY=your_key_here
```

### Run
```bash
cd backend
python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000` in a browser.

### Mobile (requires HTTPS for camera + GPS)
```bash
ngrok http 8000
# Open the https:// ngrok URL on your phone
```

### Kill ghost processes on port 8000 (Windows)
```powershell
Get-NetTCPConnection -LocalPort 8000 -State Listen | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
```

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | Landing page |
| `GET` | `/app.html` | Main app |
| `GET` | `/config` | Returns Maps API key + poll interval |
| `POST` | `/locate` | lat/lon → reverse geocode → scene → Lyria |
| `POST` | `/scan` | image + lat/lon → Gemini vision → pin + Lyria |
| `GET` | `/pins` | All active scan pins (shared across clients) |
| `GET` | `/audio/clip` | Latest Lyria-generated MP3 |
| `GET` | `/scene/current` | Current scene + location info |

---

## Project Structure

```
seeniq/
├── frontend/
│   ├── index.html          # Landing page (Three.js globe)
│   ├── app.html            # Main app (iPod UI + map)
│   ├── app.js              # GPS loop, scan flow, audio, map rendering
│   └── style.css           # Retro LCD aesthetic
├── backend/
│   ├── main.py             # FastAPI server, all endpoints
│   ├── gemini_vision.py    # Gemini vision → SceneDescription
│   ├── lyria_music.py      # Lyria 3 clip generation + session
│   ├── location_mapper.py  # Nominatim geocoding, 22 place presets
│   ├── scene_mapper.py     # Scene change threshold logic
│   └── .env                # API keys (not committed)
└── .gitignore
```

---

## Notes

- Pins are stored in memory — a server restart clears all pins
- Lyria clip generation takes ~5–10 seconds; music starts after the first clip is ready
- `lyria-realtime-exp` (infinite streaming) requires special API access not available on standard keys; clip-based looping is used instead
