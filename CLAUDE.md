# Seenic

## What this is
A crowdsourced music map app for the Google Gemini UCLA Hackathon (due 2 PM March 28, 2026).
GPS + Google Maps → Gemini understands location → Lyria 3 generates adaptive music clips → users scan surroundings to pin music to the map.

## Tech stack
- Frontend: HTML/JS/CSS, Google Maps JavaScript API
- Backend: Python FastAPI (uvicorn), Python in conda base env
- APIs: Gemini 2.0 Flash (vision), Lyria 3 clip-preview (music), Google Maps JavaScript API, Nominatim (geocoding)

## Design aesthetic
Retro green-on-black LCD style (iPod Classic era). Press Start 2P pixel font for headers, Chakra Petch for track info. Muted sage green `#72b872` (not neon). Map styled as light sage schematic. Bottom half = iPod click wheel player UI. Phone shell constrained to 390px width even on desktop.

## Prize tracks
- Best Use of Live API
- Best Use of Lyria
- Best Overall App

## Key files
- `backend/main.py` — FastAPI server, all REST endpoints
- `backend/lyria_music.py` — Lyria 3 clip generation (LyriaSession class, clip-based)
- `backend/gemini_vision.py` — Gemini vision → SceneDescription (uses `gemini-2.0-flash`)
- `backend/location_mapper.py` — Nominatim reverse geocoding, 22 place presets, zone colors
- `backend/scene_mapper.py` — SceneDescription dataclass, `should_update()` threshold logic
- `backend/.env` — API keys (GEMINI_API_KEY, GOOGLE_MAPS_API_KEY)
- `backend/test_lyria.py` — diagnostic: tests all Lyria model names via live.music.connect
- `backend/test_lyria3.py` — diagnostic: tests Lyria 3 via generate_content (confirmed working)
- `frontend/index.html` — Shell: map div, scan overlay, iPod LCD panel, click wheel
- `frontend/app.js` — Google Maps init, GPS loop, clip-based audio, scan flow
- `frontend/style.css` — All styles (phone shell, LCD, click wheel, scan overlay)
- `frontend/audio-processor.js` — Legacy AudioWorklet (no longer used, kept for reference)

## Running the server
```bash
cd backend
python -m uvicorn main:app --host 0.0.0.0 --port 8000
```
Then open http://localhost:8000

To kill ghost processes on port 8000 (run in PowerShell):
```powershell
Get-NetTCPConnection -LocalPort 8000 -State Listen | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
```

## API endpoints
- `GET  /config` — returns Maps key + interval config to frontend
- `POST /locate` — lat/lon → reverse geocode → steer Lyria (passive GPS mode)
- `POST /scan` — image + lat/lon → Gemini vision → pin + Lyria override
- `GET  /pins` — all scanned pins (in-memory, shared across clients)
- `GET  /audio/clip` — returns latest Lyria 3 MP3 clip (replaces old /ws/audio WebSocket)
- `GET  /scene/current` — latest scene + location info

## Audio architecture (IMPORTANT — switched approach)
**Old (broken):** `lyria-realtime-exp` streaming via WebSocket → PCM → AudioWorklet ring buffer
- `lyria-realtime-exp` returns HTTP 404 for all API keys tested (including hackathon key)
- This model requires special allowlist access not available

**Current (working):** `lyria-3-clip-preview` via `generate_content` → MP3 → `<audio>` element
- `models/lyria-3-clip-preview` confirmed working — generates ~700KB MP3 clips
- Also available: `models/lyria-3-pro-preview`
- Backend generates clip on scene change, stores in memory
- Frontend: `<audio>` element polls `GET /audio/clip?v={version}`, auto-refetches on end
- `refreshClip()` called from `updateNowPlaying()` to get new music on scene change
- Clip generation takes ~5-10 seconds (async background task)

## API key status
- `GOOGLE_MAPS_API_KEY`: Working ✅
- `GEMINI_API_KEY`: Working for Gemini Flash vision ✅, working for Lyria 3 clip ✅
- `lyria-realtime-exp` streaming: HTTP 404 (no access) ❌

## Known issues / pending
- First clip takes ~5-10s to generate after pressing play — consider showing a loading state
- `audio-processor.js` still in frontend/ but unused
- `test_lyria.py` and `test_lyria3.py` are debug scripts, not part of app
- `start.bat` is a convenience launcher

## Environment notes
- Windows 11, conda base env has all packages
- Run server with `python -m uvicorn` (not `conda run` — causes output buffering issues)
- Do NOT run server via Claude background tasks — creates ghost processes on port 8000




## Pitch

Pokémon GO proved that if you give people a reason to walk around and scan their environment, they will — and in doing so, they generate incredibly valuable location data. 

Seenic does the same thing, but with music. When was the last time you heard birds chirping in the morning, or the buzzing of nature? With Seenic, as you walk around, your phone generates a natural soundtrack for your surroundings for you to listen to rather than blasting noise. If you want it to be more specific, you scan, and that scan pins AI-generated music to the map for everyone. (insert video of scanning a garden and it playing garden music)

*** Insert app feature testing ***

Scan party room → coverage ring appears on map → "this is what you just contributed"
Walk away → ZONE badge disappears
Walk back in → ZONE badge pulses back → party music resumes
Second phone walks into the same circle → same badge, same music, without scanning

*** Continue pitch ***

User gets a personalized soundtrack. We get crowdsourced real-world scene data at scale of what places actually look and feel like, not just what Google Maps labels them. That's valuable to advertisers, city planners, real estate, tourism. With less people starting to go out and touch grass, it's important for us to know what drives people to step out of their rooms and enjoy nature before it's too late. 
