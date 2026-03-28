"""
lyria_music.py
Manages a persistent Lyria RealTime session.
Accepts SceneDescription updates and streams PCM audio chunks to a callback.
"""

import asyncio
import logging
import os
from collections.abc import Callable
from typing import Any

from dotenv import load_dotenv
from google import genai
from google.genai import types

from gemini_vision import SceneDescription

load_dotenv()

logger = logging.getLogger(__name__)

# Lyria outputs 48 kHz stereo PCM (16-bit little-endian)
LYRIA_SAMPLE_RATE = 48_000
LYRIA_CHANNELS = 2
LYRIA_BITS = 16

AudioCallback = Callable[[bytes], Any]


class LyriaSession:
    """
    Wraps a single Lyria RealTime session.

    Usage:
        session = LyriaSession(on_audio=my_callback)
        await session.start()
        await session.update_scene(scene_description)
        ...
        await session.stop()
    """

    def __init__(self, on_audio: AudioCallback) -> None:
        self._on_audio = on_audio
        self._session: Any = None          # google-genai live music session
        self._client: genai.Client | None = None
        self._receive_task: asyncio.Task | None = None
        self._running = False
        self._current_scene: SceneDescription | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Open a connection to Lyria RealTime and start receiving audio."""
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY is not set in environment / .env")

        self._client = genai.Client(api_key=api_key)
        self._running = True

        # The session is entered as an async context manager; we keep a
        # reference so we can steer it later from update_scene().
        self._cm = self._client.aio.live.music.connect(model="lyria-realtime-exp")
        self._session = await self._cm.__aenter__()

        # Kick off with a neutral ambient prompt so audio starts immediately
        await self._send_defaults()

        self._receive_task = asyncio.create_task(self._receive_loop())
        logger.info("Lyria session started")

    async def stop(self) -> None:
        """Close the Lyria session gracefully."""
        self._running = False
        if self._receive_task:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass
        if hasattr(self, "_cm") and self._cm and self._session:
            try:
                await self._cm.__aexit__(None, None, None)
            except Exception:
                pass
        self._session = None
        logger.info("Lyria session stopped")

    # ------------------------------------------------------------------
    # Steering
    # ------------------------------------------------------------------

    async def update_scene(self, scene: SceneDescription) -> None:
        """
        Steer Lyria to match the new scene description.
        Called whenever a significant scene change is detected.
        """
        if self._session is None:
            logger.warning("update_scene called before session started — ignoring")
            return

        self._current_scene = scene
        prompt_text = scene.to_lyria_prompt()

        logger.info("Steering Lyria → %s (BPM=%s, energy=%.2f)", prompt_text, scene.suggested_bpm, scene.energy)

        await self._session.set_weighted_prompts(
            [types.WeightedPrompt(text=prompt_text, weight=1.0)]
        )

        await self._session.set_music_generation_config(
            types.MusicGenerationConfig(
                bpm=scene.suggested_bpm,
                density=scene.density,
                guidance=scene.guidance,
            )
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _send_defaults(self) -> None:
        """Send a neutral starting prompt so music begins immediately."""
        await self._session.set_weighted_prompts(
            [types.WeightedPrompt(text="ambient, calm, neutral", weight=1.0)]
        )
        await self._session.set_music_generation_config(
            types.MusicGenerationConfig(bpm=80, density=0.3, guidance=4.0)
        )

    async def _receive_loop(self) -> None:
        """Continuously receive audio chunks and forward to the callback."""
        try:
            async for message in self._session.receive():
                if not self._running:
                    break
                if message.server_content and message.server_content.audio_chunks:
                    for chunk in message.server_content.audio_chunks:
                        self._on_audio(chunk.data)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error("Lyria receive loop error: %s — attempting reconnect in 3s", exc)
            await asyncio.sleep(3)
            if self._running:
                logger.info("Reconnecting to Lyria...")
                try:
                    await self.stop()
                    await self.start()
                    # Re-steer to the last known scene after reconnect
                    if self._current_scene:
                        await self.update_scene(self._current_scene)
                except Exception as reconnect_exc:
                    logger.error("Lyria reconnect failed: %s", reconnect_exc)
