"""
main.py
FastAPI server for Seenic.

Endpoints:
  GET  /config              — runtime config
  POST /locate              — lat/lng → reverse geocode → steer Lyria (passive mode)
  POST /scan                — image + lat/lng → Gemini vision → steer Lyria + save pin
  GET  /pins                — all scanned location pins
  POST /scene/preset/:mood  — manual mood override
  GET  /scene/current       — latest scene + location
  WS   /ws/audio            — continuous PCM audio stream from Lyria

Run:
  uvicorn main:app --reload --host 0.0.0.0 --port 8000
"""

import asyncio
import logging
import math
import os
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass, field

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from gemini_vision import SceneDescription, analyze_frame
from location_mapper import LocationInfo, location_to_scene, reverse_geocode
from lyria_music import LyriaSession
from scene_mapper import fallback_scene, should_update

from pathlib import Path
_env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(_env_path)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
logger.info("ENV loaded from %s", _env_path)
logger.info("GOOGLE_MAPS_API_KEY present: %s", bool(os.getenv("GOOGLE_MAPS_API_KEY")))

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

PIN_RADIUS_M = 30       # metres — within this distance a scanned pin overrides passive GPS
PIN_TTL_S    = 15 * 60  # 15 minutes — how long a scanned pin influences the area


@dataclass
class Pin:
    id: str
    lat: float
    lon: float
    place_type: str
    display_name: str
    scene_description: str
    genre: str
    bpm: int
    zone_color: str
    timestamp: float = field(default_factory=time.time)
    scene: SceneDescription | None = field(default=None, repr=False)  # full scene for location memory


# ---------------------------------------------------------------------------
# Location memory helpers
# ---------------------------------------------------------------------------

def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def find_nearby_scene(lat: float, lon: float) -> SceneDescription | None:
    """
    Return the SceneDescription of the nearest live pin within PIN_RADIUS_M and PIN_TTL_S.
    Returns None if no qualifying pin exists.
    """
    now = time.time()
    best_dist = float("inf")
    best_scene: SceneDescription | None = None
    for pin in pins.values():
        if pin.scene is None:
            continue
        if now - pin.timestamp > PIN_TTL_S:
            continue
        dist = _haversine_m(lat, lon, pin.lat, pin.lon)
        if dist <= PIN_RADIUS_M and dist < best_dist:
            best_dist = dist
            best_scene = pin.scene
    return best_scene


# ---------------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------------

lyria: LyriaSession | None = None
current_scene: SceneDescription | None = None
previous_scene: SceneDescription | None = None
current_location: LocationInfo | None = None
pins: dict[str, Pin] = {}


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    global lyria
    lyria = LyriaSession()
    try:
        await lyria.start()
        logger.info("Lyria session ready")
    except Exception as exc:
        logger.warning("Could not start Lyria: %s", exc)
    yield
    if lyria:
        await lyria.stop()


app = FastAPI(title="Seenic", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# REST endpoints
# ---------------------------------------------------------------------------

@app.get("/config")
async def get_config():
    return {
        "locate_interval_ms": int(os.getenv("LOCATE_INTERVAL_SECONDS", "5")) * 1000,
        "change_threshold": float(os.getenv("SCENE_CHANGE_THRESHOLD", "0.15")),
        "maps_api_key": os.getenv("GOOGLE_MAPS_API_KEY", ""),
    }


class LocateRequest(BaseModel):
    lat: float
    lon: float


@app.post("/locate")
async def locate_endpoint(body: LocateRequest):
    """Passive mode: reverse-geocode GPS coordinates and steer Lyria."""
    global current_scene, previous_scene, current_location

    try:
        info = await reverse_geocode(body.lat, body.lon)
    except Exception as exc:
        logger.warning("Nominatim error: %s — using cached scene", exc)
        if current_scene and current_location:
            return {
                "scene": {**asdict(current_scene), "_cached": True},
                "zone_color": current_location.zone_color,
                "place_type": current_location.place_type,
                "display_name": current_location.display_name,
            }
        raise HTTPException(status_code=502, detail=f"Geocoding error: {exc}")

    current_location = info

    # Location memory: if a recently scanned pin is nearby, use its scene instead
    nearby = find_nearby_scene(body.lat, body.lon)
    scene = nearby if nearby is not None else location_to_scene(info)
    previous_scene = current_scene
    current_scene = scene

    if lyria and should_update(previous_scene, current_scene):
        asyncio.create_task(lyria.interpolate_to_scene(current_scene))
        source = "pin-memory" if nearby else "gps"
        logger.info("[%s] Zone: %s (%s) → %s @ %s BPM",
                    source, info.display_name, info.place_type, scene.suggested_genre, scene.suggested_bpm)

    return {
        "scene": asdict(current_scene),
        "zone_color": info.zone_color,
        "place_type": info.place_type,
        "display_name": info.display_name,
        "memory_active": nearby is not None,
    }


@app.post("/scan")
async def scan_endpoint(
    file: UploadFile = File(...),
    lat: float = Form(...),
    lon: float = Form(...),
):
    """
    Active scan mode: analyze camera image with Gemini vision, steer Lyria immediately,
    and save a pin at the given coordinates.
    """
    global current_scene, previous_scene, current_location

    image_bytes = await file.read()

    # Strip codec params (e.g. "video/webm;codecs=vp8" → "video/webm") — Gemini rejects the suffix
    raw_mime = file.content_type or "image/jpeg"
    mime_type = raw_mime.split(";")[0].strip()

    try:
        scene = await analyze_frame(image_bytes, mime_type)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Gemini vision error: {exc}")

    try:
        info = await reverse_geocode(lat, lon)
    except Exception:
        info = LocationInfo(
            lat=lat, lon=lon,
            place_type="default",
            display_name=scene.setting,
            zone_color="#7c6af7",
        )

    current_location = info
    previous_scene = current_scene
    current_scene = scene

    # Immediate update (no interpolation — user expects instant response on scan)
    if lyria:
        await lyria.update_scene(scene)
        logger.info("Scan pin: %s → %s @ %s BPM", info.display_name, scene.suggested_genre, scene.suggested_bpm)

    pin = Pin(
        id=str(uuid.uuid4()),
        lat=lat,
        lon=lon,
        place_type=info.place_type,
        display_name=info.display_name,
        scene_description=scene.setting,
        genre=scene.suggested_genre,
        bpm=scene.suggested_bpm,
        zone_color=info.zone_color,
        scene=scene,  # stored for location memory
    )
    pins[pin.id] = pin

    return {"scene": asdict(scene), "pin": asdict(pin)}


@app.get("/pins")
async def get_pins():
    """Return all scanned location pins (shared across all connected clients)."""
    return {"pins": [asdict(p) for p in pins.values()]}


@app.post("/scene/preset/{mood}")
async def preset_scene_endpoint(mood: str):
    global current_scene, previous_scene
    scene = fallback_scene(mood)
    previous_scene = current_scene
    current_scene = scene
    if lyria:
        await lyria.update_scene(current_scene)
    return {"status": "ok", "scene": asdict(current_scene)}


@app.get("/scene/current")
async def get_current_scene():
    return {
        "scene": asdict(current_scene) if current_scene else None,
        "location": {
            "zone_color": current_location.zone_color,
            "place_type": current_location.place_type,
            "display_name": current_location.display_name,
        } if current_location else None,
    }


# ---------------------------------------------------------------------------
# Audio clip endpoint (Lyria 3 clip-based)
# ---------------------------------------------------------------------------

@app.get("/audio/clip")
async def audio_clip():
    """Return the latest Lyria-generated MP3 clip for the current scene."""
    if not lyria:
        raise HTTPException(status_code=503, detail="Lyria not initialised")
    clip = lyria.get_clip()
    if not clip:
        raise HTTPException(status_code=503, detail="Clip not ready yet")
    return Response(content=clip, media_type="audio/mpeg")


# ---------------------------------------------------------------------------
# Static files — must be mounted LAST so API routes take priority
# ---------------------------------------------------------------------------

_frontend_path = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.isdir(_frontend_path):
    app.mount("/", StaticFiles(directory=_frontend_path, html=True), name="frontend")
