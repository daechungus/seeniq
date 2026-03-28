"""
Diagnostic script -- tests Lyria connectivity exhaustively.
Run: conda run -n base python test_lyria.py
"""
import asyncio
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

from google import genai

api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
print("API key loaded:", bool(api_key), ("(" + api_key[:12] + "...)") if api_key else "")

client = genai.Client(api_key=api_key)

# 1. List models filtered for live/lyria
print("\n=== Models (live/lyria/music/realtime) ===")
try:
    for m in client.models.list():
        if any(x in m.name.lower() for x in ("lyria", "live", "music", "realtime")):
            print(" ", m.name)
except Exception as e:
    print("  models.list() error:", e)

# 2. Try each candidate model name
MODEL_CANDIDATES = [
    "lyria-realtime-exp",
    "lyria-realtime-exp-003",
    "lyria-realtime",
    "models/lyria-realtime-exp",
    "lyria-3-clip-preview",
    "models/lyria-3-clip-preview",
    "lyria-3-pro-preview",
    "models/lyria-3-pro-preview",
]

async def try_connect(model_name):
    print("\n--- Trying:", model_name, "---")
    try:
        async with client.aio.live.music.connect(model=model_name) as session:
            await session.set_weighted_prompts(
                [genai.types.WeightedPrompt(text="ambient calm", weight=1.0)]
            )
            await session.set_music_generation_config(
                genai.types.MusicGenerationConfig(bpm=80, density=0.3, guidance=4.0)
            )
            async for msg in session.receive():
                if msg.server_content and msg.server_content.audio_chunks:
                    size = sum(len(c.data) for c in msg.server_content.audio_chunks)
                    print("  CONNECTED - received audio chunk:", size, "bytes")
                    return True
                break
    except Exception as e:
        print("  FAILED:", type(e).__name__, str(e)[:120])
    return False

async def main():
    for name in MODEL_CANDIDATES:
        success = await try_connect(name)
        if success:
            print("\nUSE THIS MODEL:", name)
            return
    print("\nNo Lyria model connected. Key lacks access or model name changed.")

asyncio.run(main())
