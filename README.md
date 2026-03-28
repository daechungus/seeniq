# Seenic — The World Has a Soundtrack

> Built for the Google Gemini UCLA Hackathon 2026

---

## Inspiration

We've all had the experience of walking into a place and feeling like it needs a soundtrack — a quiet library that deserves hushed piano, a packed gym that should be pounding with energy, a rooftop at golden hour that feels cinematic. Music shapes how we experience spaces, but we've always had to curate it manually.

Pokémon GO proved that people will attach meaning to physical locations and share it with strangers. Spotify proved that music is deeply tied to context. We asked: what if those two ideas merged? What if the world itself had a living, evolving musical layer — one that you could contribute to and experience just by walking through it?

That's Seenic.

---

## What It Does

Seenic generates original music in real time based on where you are and what you see.

**Passive mode:** As you move through the world, your GPS location is reverse-geocoded and matched to a place archetype — park, café, nightclub, library, hospital, beach, and 18 others. Lyria 3 composes music that fits that context. Walk from a quiet residential street into a commercial district and the music shifts with you.

**Active scan:** Tap the camera button. Seenic opens your camera, captures a frame, and sends it to Gemini Vision. Gemini doesn't just see "outdoor space" — it reads the energy, the lighting, the mood, the density of the scene, and returns a structured musical brief: genre, BPM, emotional tone. Lyria composes something for that exact moment.

**The map:** Every scan drops a pin on a shared map with a 30-meter influence radius. That pin lives for 15 minutes. Anyone who walks into that zone — from anywhere in the world — hears what you heard. A pulsing ZONE badge appears on their player. The musical layer of the world is built, one scan at a time.

---

## How We Built It

The stack is intentionally minimal so the AI does the heavy lifting.

**Frontend** — Vanilla HTML, CSS, and JavaScript. A Google Maps view occupies the top half; a custom iPod Classic–inspired click wheel player sits on the bottom. As you move, colored breadcrumb circles paint your trail on the map. Scan pins appear as arrows with glowing coverage rings. A live waveform visualizer pulses with the music.

**Backend** — Python FastAPI server with a handful of endpoints. GPS coordinates come in, Nominatim (OpenStreetMap) reverse-geocodes them for free, and a scene preset is selected from 22 hand-tuned place archetypes. The server holds all pins in a shared in-memory store — no database needed for a demo.

**Gemini 2.5 Flash Lite** handles vision. We send it a JPEG frame and a strict prompt that forces structured JSON output: mood, energy (0–1), BPM, genre, musical density, and a guidance scalar. The response reliably parses into a `SceneDescription` object that drives Lyria.

**Lyria 3 Clip Preview** generates the music. We pass a text prompt built from the scene description and receive a ~47-second MP3 that loops until the scene changes. When it does, a new clip generates in the background while the current one keeps playing.

The landing page features a Three.js particle globe with an intro animation — particles flow from scattered jitter into a sphere — and an exit animation where the globe expands outward into nothing as you enter the map.

---

## Challenges We Ran Into

**Gemini model availability.** Our initial target model (`gemini-2.0-flash`) returned 404 on our API key mid-build. We had to write a live model discovery script to probe which models were actually accessible, eventually landing on `gemini-2.5-flash-lite` for vision — which turned out to be faster anyway.

**Lyria RealTime vs. Lyria 3.** The architecture we envisioned used `lyria-realtime-exp` — a persistent WebSocket that streams infinite music and morphs in real time as you steer it with new prompts. That's the right model for Seenic. It returned HTTP 404 for all keys we tested. We pivoted to clip-based generation with `lyria-3-clip-preview`, which works and sounds great, but doesn't morph continuously.

**Video vs. image for Gemini Vision.** We originally wanted to send a 3-second video scan for richer context. Gemini's `generate_content` endpoint doesn't support inline video bytes — that requires the File API, which adds latency and complexity. We switched to single JPEG frames, which Gemini handles instantly and analyzes with surprising depth.

**HTTPS on physical devices.** Camera and GPS both require a secure context in mobile browsers. Running the server locally means demos on a physical phone need ngrok. This added an extra step to every test iteration.

---

## What Makes Seenic Different

Most music apps are passive. You pick a playlist, it plays. The music has nothing to do with where you are or what's around you — it's pulled from a library, not generated for the moment.

Seenic generates music that has never existed before, for a place that exists right now, informed by what the camera actually sees. It's not a recommendation engine. It's not a mood filter on a playlist. It's composition on demand, triggered by physical presence.

The crowdsourcing layer is what separates it further. Other generative music apps are solitary experiences. Seenic makes the world itself into a collaborative instrument. Scan a party — everyone who walks through that door for the next 15 minutes hears party music. Scan a sunrise — the strangers who show up after you get the same gift you gave yourself.

No other app builds a living musical map of the real world as people move through it.

---

## What We're Proud Of

The scan-to-music pipeline working end-to-end in under 15 seconds. Point a camera at something, get original music back that genuinely fits what you were looking at — that moment still feels like magic every time.

The location memory system. The fact that a scan you made 10 minutes ago affects the experience of someone who has never met you, just because they walked close enough — that's the whole thesis of the app, working in code.

The UI. The iPod click wheel aesthetic wasn't just cosmetic. It gave the app a strong identity and made the demo immediately intuitive. People knew what it was before we explained it.

The landing page globe. Particles flowing into a sphere on load, then exploding outward when you enter the map — it took one afternoon and it sells the concept before a single word is read.

---

## What We Learned

Gemini Vision is genuinely good at reading *feel*. We expected it to identify objects. Instead it returned things like "hushed reading room, warm afternoon light, contemplative" — which made for much better music prompts than "library, indoors, people."

Structured JSON output from an LLM is reliable when the prompt is strict. Having Gemini return a bounded schema (mood from a fixed list, energy as 0–1 float, BPM as integer) meant zero post-processing failures across hundreds of test scans.

Clip-based generation can feel continuous with the right UX. A 47-second loop that refreshes in the background on scene change — with a brief crossover period — feels live even when it isn't. The perception of continuity matters more than actual streaming.

Building for a physical demo changes everything. GPS accuracy, camera warmup time, HTTPS requirements on mobile, network latency to the geocoding API — none of these exist in unit tests. The last two hours of every hackathon are really about making the demo path bulletproof.

---

## What's Next

**Lyria RealTime integration.** When `lyria-realtime-exp` access becomes available, the entire passive GPS loop should drive real-time prompt steering over a persistent WebSocket. The music would never stop — it would just slowly become something else as you move. That's the version of Seenic we built toward.

**Persistent pin storage.** Right now pins live in server memory and vanish on restart. A database (even SQLite) would let the musical map persist and grow over time, building a historical record of what people heard where.

**Social layer.** Show who scanned a zone. Let users name their scans. Notify you when someone walks into music you created. Build the social graph of the musical world.

**Richer scene analysis.** The current prompt extracts seven fields from a single frame. With video support (Gemini File API) and multi-frame analysis, the scene understanding could capture movement, crowd density, time of day — producing far more nuanced musical briefs.

**Wearable / ambient mode.** Seenic should run in your pocket, updating silently as you move, with no interaction required. The scan button is for intentional moments. The rest should just happen.

---

## Setup

### Prerequisites
- Anaconda (base environment)
- API keys: `GEMINI_API_KEY`, `GOOGLE_MAPS_API_KEY`

### Install dependencies
```bash
pip install fastapi uvicorn python-dotenv httpx google-genai pillow
```

### Configure keys
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

Open `http://localhost:8000`. For mobile, use ngrok for HTTPS.

---

## Project Structure

```
seeniq/
├── frontend/
│   ├── index.html          # Landing page (Three.js particle globe)
│   ├── app.html            # Main app (iPod UI + live map)
│   ├── app.js              # GPS loop, scan flow, audio, map rendering
│   └── style.css           # Retro green-on-black LCD aesthetic
├── backend/
│   ├── main.py             # FastAPI server, all endpoints, pin memory
│   ├── gemini_vision.py    # Camera frame → Gemini → SceneDescription
│   ├── lyria_music.py      # SceneDescription → Lyria 3 → MP3 clip
│   ├── location_mapper.py  # Nominatim geocoding, 22 place presets
│   ├── scene_mapper.py     # Scene change threshold logic
│   └── .env                # API keys (gitignored)
└── .gitignore
```


# full stack

frontend is a web app with html css and js

backend is using python with fastapi

used gemini live api for real time camera analysis to understand the environment

used lyria 3 to generate continuous music.

used google maps place api to get the gps coordinates




Imagine if every single moment in the world had its own unique soundtrack. Not a playlist that was created by someone else, but it's own tailored music for every situation you were in. 
That's what seenic is. Whether you're at a party, or studying at a cafe, every moment you're in has a score that generates its own music in the world. 

every single moment had its unique soundtrack

SEENIC transforms every moment

experience the world only by going outside


Every place, every moment, every person, all get a score and soundtrack generated by an AI. 

The world becomes a music experience that you can only unlock by going outside and experiencing it yourself. 