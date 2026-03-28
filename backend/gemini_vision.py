"""
gemini_vision.py
Sends a camera frame to Gemini and returns a structured scene description.
"""

import json
import os
import re
from dataclasses import dataclass

from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY is not set in environment / .env")
        _client = genai.Client(api_key=api_key)
    return _client


SCENE_PROMPT = """
Analyze this image and return ONLY a JSON object with the following fields.
No markdown, no explanation — raw JSON only.

{
  "mood": "<one word: calm | tense | melancholic | joyful | mysterious | energetic | romantic | dark | peaceful | chaotic>",
  "energy": <float 0.0 to 1.0, where 0=still/quiet, 1=busy/intense>,
  "setting": "<brief phrase describing the scene, e.g. 'sunlit park, afternoon'>",
  "suggested_genre": "<music genre phrase, e.g. 'ambient acoustic', 'lo-fi hip hop', 'upbeat electronic'>",
  "suggested_bpm": <integer 50-180>,
  "density": <float 0.0 to 1.0, musical density/busyness>,
  "guidance": <float 1.0 to 6.0, how closely to follow the prompt — higher = more literal>
}

Be creative but accurate. The music will be generated to match this scene.
"""


@dataclass
class SceneDescription:
    mood: str
    energy: float
    setting: str
    suggested_genre: str
    suggested_bpm: int
    density: float
    guidance: float

    def to_lyria_prompt(self) -> str:
        return f"{self.suggested_genre}, {self.mood} atmosphere, {self.setting}"


async def analyze_frame(image_bytes: bytes, mime_type: str = "image/jpeg") -> SceneDescription:
    """
    Send a raw image frame to Gemini and return a SceneDescription.

    Args:
        image_bytes: Raw bytes of the captured frame.
        mime_type: MIME type of the image (default: image/jpeg).

    Returns:
        SceneDescription parsed from Gemini's response.
    """
    client = _get_client()

    image_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)

    response = await client.aio.models.generate_content(
        model="gemini-2.0-flash-exp",
        contents=[image_part, SCENE_PROMPT],
        config=types.GenerateContentConfig(
            temperature=0.4,
            max_output_tokens=256,
        ),
    )

    raw = response.text.strip()

    # Extract the first JSON object found, regardless of surrounding markdown
    match = re.search(r'\{.*\}', raw, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON object in Gemini response: {raw[:200]}")
    data = json.loads(match.group())

    return SceneDescription(
        mood=data.get("mood", "calm"),
        energy=float(data.get("energy", 0.5)),
        setting=data.get("setting", "unknown scene"),
        suggested_genre=data.get("suggested_genre", "ambient"),
        suggested_bpm=int(data.get("suggested_bpm", 90)),
        density=float(data.get("density", 0.5)),
        guidance=float(data.get("guidance", 4.0)),
    )
