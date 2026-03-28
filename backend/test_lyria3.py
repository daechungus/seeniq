"""
Test Lyria 3 clip generation via generate_content API.
Run: conda run -n base python test_lyria3.py
"""
import asyncio
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

from google import genai
from google.genai import types

api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
print("Key:", api_key[:12] + "..." if api_key else "MISSING")

client = genai.Client(api_key=api_key)

async def test_lyria3_clip():
    print("\n--- Testing lyria-3-clip-preview via generate_content ---")
    try:
        response = await client.aio.models.generate_content(
            model="models/lyria-3-clip-preview",
            contents="Generate ambient calm background music, 80 BPM, peaceful park scene.",
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
            ),
        )
        print("Response:", response)
        for part in response.candidates[0].content.parts:
            if hasattr(part, 'inline_data') and part.inline_data:
                print("Got audio! mime:", part.inline_data.mime_type, "size:", len(part.inline_data.data))
                with open("test_output.wav", "wb") as f:
                    f.write(part.inline_data.data)
                print("Saved to test_output.wav")
                return True
            else:
                print("Part:", part)
    except Exception as e:
        print("FAILED:", type(e).__name__, str(e)[:200])
    return False

async def test_lyria3_pro():
    print("\n--- Testing lyria-3-pro-preview via generate_content ---")
    try:
        response = await client.aio.models.generate_content(
            model="models/lyria-3-pro-preview",
            contents="Ambient calm background music, 80 BPM, peaceful.",
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
            ),
        )
        print("Response:", response)
        for part in response.candidates[0].content.parts:
            if hasattr(part, 'inline_data') and part.inline_data:
                print("Got audio! mime:", part.inline_data.mime_type, "size:", len(part.inline_data.data))
                return True
    except Exception as e:
        print("FAILED:", type(e).__name__, str(e)[:200])
    return False

async def main():
    r1 = await test_lyria3_clip()
    if not r1:
        await test_lyria3_pro()

asyncio.run(main())
