"""
lyria_music.py
Generates music clips using Lyria 3 (lyria-3-clip-preview).
Switched from streaming lyria-realtime-exp (HTTP 404) to clip-based approach.
"""

import asyncio
import logging
import os
from pathlib import Path
from dotenv import load_dotenv
from google import genai
from google.genai import types

from gemini_vision import SceneDescription

load_dotenv(Path(__file__).resolve().parent / ".env")

logger = logging.getLogger(__name__)


def _get_client() -> genai.Client:
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("Neither GEMINI_API_KEY nor GOOGLE_API_KEY is set in .env")
    return genai.Client(api_key=api_key)


class LyriaSession:
    """
    Generates MP3 clips using Lyria 3 (lyria-3-clip-preview).
    When the scene changes, a new clip is generated and stored.
    Clients fetch it via GET /audio/clip.
    """

    def __init__(self) -> None:
        self._client: genai.Client | None = None
        self._current_scene: SceneDescription | None = None
        self._current_clip: bytes | None = None          # latest MP3 bytes
        self._generating = False
        self._running = False

    async def start(self) -> None:
        self._client = _get_client()
        self._running = True
        # Generate a neutral starting clip
        from gemini_vision import SceneDescription as SD
        default = SD(
            mood="calm", energy=0.3, setting="neutral ambient space",
            suggested_genre="ambient", suggested_bpm=80,
            density=0.3, guidance=4.0,
        )
        await self.update_scene(default)
        logger.info("LyriaSession started (clip mode)")

    async def stop(self) -> None:
        self._running = False
        logger.info("LyriaSession stopped")

    def get_clip(self) -> bytes | None:
        """Return the latest generated MP3 clip, or None if not ready."""
        return self._current_clip

    async def update_scene(self, scene: SceneDescription) -> None:
        """Generate a new clip for this scene (non-blocking — fires a background task)."""
        self._current_scene = scene
        if not self._generating:
            asyncio.create_task(self._generate_clip(scene))

    async def interpolate_to_scene(self, target: SceneDescription, steps: int = 3) -> None:
        """For passive mode, just go directly to target (clip-based, no interpolation needed)."""
        await self.update_scene(target)

    async def _generate_clip(self, scene: SceneDescription) -> None:
        if self._generating or not self._client:
            return
        self._generating = True
        prompt = (
            f"{scene.suggested_genre}, {scene.mood} atmosphere, {scene.setting}. "
            f"BPM around {scene.suggested_bpm}. "
            f"Energy level {'high' if scene.energy > 0.6 else 'low' if scene.energy < 0.35 else 'medium'}."
        )
        logger.info("Generating Lyria clip: %s", prompt[:80])
        try:
            response = await self._client.aio.models.generate_content(
                model="models/lyria-3-clip-preview",
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                ),
            )
            for part in response.candidates[0].content.parts:
                if part.inline_data and part.inline_data.mime_type.startswith("audio"):
                    self._current_clip = part.inline_data.data
                    logger.info("Lyria clip ready: %d bytes", len(self._current_clip))
                    break
        except Exception as exc:
            logger.error("Lyria clip generation failed: %s", exc)
        finally:
            self._generating = False
