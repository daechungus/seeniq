"""
main.py
FastAPI server for MusicMap.

Endpoints:
  GET  /config              — runtime config
  POST /locate              — lat/lng → reverse geocode → steer Lyria → return zone info
  POST /scene/preset/:mood  — manual mood override
  GET  /scene/current       — latest scene
  WS   /ws/audio            — continuous PCM audio stream from Lyria

Run:
  uvicorn main:app --reload --host 0.0.0.0 --port 8000
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from dataclasses import asdict

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from gemini_vision import SceneDescription
from location_mapper import LocationInfo, location_to_scene, reverse_geocode
from lyria_music import LyriaSession
from scene_mapper import fallback_scene, should_update

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------------

lyria: LyriaSession | None = None
current_scene: SceneDescription | None = None
previous_scene: SceneDescription | None = None
current_location: LocationInfo | None = None

audio_clients: set[WebSocket] = set()


def _broadcast_audio(pcm_bytes: bytes) -> None:
    dead = set()
    for ws in audio_clients:
        try:
            asyncio.get_event_loop().create_task(ws.send_bytes(pcm_bytes))
        except Exception:
            dead.add(ws)
    audio_clients.difference_update(dead)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    global lyria
    lyria = LyriaSession(on_audio=_broadcast_audio)
    try:
        await lyria.start()
        logger.info("Lyria session ready")
    except Exception as exc:
        logger.warning("Could not start Lyria (no API key yet?): %s", exc)
    yield
    if lyria:
        await lyria.stop()


app = FastAPI(title="MusicMap", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_frontend_path = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.isdir(_frontend_path):
    app.mount("/", StaticFiles(directory=_frontend_path, html=True), name="frontend")


# ---------------------------------------------------------------------------
# REST endpoints
# ---------------------------------------------------------------------------

@app.get("/config")
async def get_config():
    return {
        "locate_interval_ms": int(os.getenv("LOCATE_INTERVAL_SECONDS", "5")) * 1000,
        "change_threshold": float(os.getenv("SCENE_CHANGE_THRESHOLD", "0.15")),
    }


class LocateRequest(BaseModel):
    lat: float
    lon: float


@app.post("/locate")
async def locate_endpoint(body: LocateRequest):
    """
    Reverse-geocode the given coordinates, map to a music scene, and steer Lyria.
    Returns zone info for the frontend map overlay.
    """
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
    scene = location_to_scene(info)

    previous_scene = current_scene
    current_scene = scene

    if lyria and should_update(previous_scene, current_scene):
        asyncio.create_task(lyria.update_scene(current_scene))
        logger.info("Zone: %s (%s) → %s @ %s BPM", info.display_name, info.place_type, scene.suggested_genre, scene.suggested_bpm)

    return {
        "scene": asdict(current_scene),
        "zone_color": info.zone_color,
        "place_type": info.place_type,
        "display_name": info.display_name,
    }


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
# WebSocket — audio stream
# ---------------------------------------------------------------------------

@app.websocket("/ws/audio")
async def audio_websocket(ws: WebSocket):
    """Stream raw 48 kHz stereo 16-bit LE PCM audio to the browser."""
    await ws.accept()
    audio_clients.add(ws)
    logger.info("Audio client connected (%d total)", len(audio_clients))
    try:
        await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        audio_clients.discard(ws)
        logger.info("Audio client disconnected (%d remaining)", len(audio_clients))
