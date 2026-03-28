"""
scene_mapper.py
Decides whether a new SceneDescription is different enough from the last one
to warrant steering Lyria, and provides helper utilities.
"""

import math
import os

from gemini_vision import SceneDescription

# How much the combined scene vector must change before we steer Lyria.
# Prevents constant micro-adjustments from every frame.
DEFAULT_THRESHOLD = float(os.getenv("SCENE_CHANGE_THRESHOLD", "0.15"))


def scene_distance(a: SceneDescription, b: SceneDescription) -> float:
    """
    Euclidean distance between two scenes in (energy, density, bpm_norm) space.
    BPM is normalised to [0,1] assuming range 50–180.
    """
    bpm_range = 180 - 50
    bpm_a = (a.suggested_bpm - 50) / bpm_range
    bpm_b = (b.suggested_bpm - 50) / bpm_range

    return math.sqrt(
        (a.energy - b.energy) ** 2
        + (a.density - b.density) ** 2
        + (bpm_a - bpm_b) ** 2
    )


def should_update(
    previous: SceneDescription | None,
    current: SceneDescription,
    threshold: float = DEFAULT_THRESHOLD,
) -> bool:
    """
    Return True if the scene has changed enough to steer Lyria.
    Always returns True on the first call (previous is None).
    """
    if previous is None:
        return True
    return scene_distance(previous, current) >= threshold


# ---------------------------------------------------------------------------
# Fallback: rule-based mapping for when Gemini is unavailable / slow
# ---------------------------------------------------------------------------

_RULE_PRESETS = {
    "calm":      dict(suggested_genre="ambient piano",         suggested_bpm=70,  density=0.2, guidance=4.0, energy=0.2),
    "peaceful":  dict(suggested_genre="acoustic guitar, folk", suggested_bpm=75,  density=0.25, guidance=4.0, energy=0.25),
    "melancholic": dict(suggested_genre="cinematic strings",   suggested_bpm=65,  density=0.3, guidance=4.5, energy=0.3),
    "mysterious": dict(suggested_genre="dark ambient, eerie",  suggested_bpm=80,  density=0.4, guidance=5.0, energy=0.4),
    "joyful":    dict(suggested_genre="ukulele pop",           suggested_bpm=110, density=0.6, guidance=4.0, energy=0.7),
    "energetic": dict(suggested_genre="upbeat electronic",     suggested_bpm=130, density=0.75, guidance=4.0, energy=0.85),
    "chaotic":   dict(suggested_genre="drum and bass",         suggested_bpm=160, density=0.9, guidance=3.5, energy=0.95),
    "tense":     dict(suggested_genre="thriller orchestral",   suggested_bpm=100, density=0.65, guidance=5.0, energy=0.6),
    "romantic":  dict(suggested_genre="jazz ballad, piano",    suggested_bpm=72,  density=0.35, guidance=4.0, energy=0.35),
    "dark":      dict(suggested_genre="lo-fi, minor keys",     suggested_bpm=85,  density=0.4, guidance=4.5, energy=0.4),
}


def fallback_scene(mood: str, setting: str = "unknown scene") -> SceneDescription:
    """
    Construct a SceneDescription from a known mood keyword using rule presets.
    Useful when Gemini is unavailable or for testing Lyria in isolation.
    """
    preset = _RULE_PRESETS.get(mood.lower(), _RULE_PRESETS["calm"])
    return SceneDescription(
        mood=mood,
        energy=preset["energy"],
        setting=setting,
        suggested_genre=preset["suggested_genre"],
        suggested_bpm=preset["suggested_bpm"],
        density=preset["density"],
        guidance=preset["guidance"],
    )
