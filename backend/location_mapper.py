"""
location_mapper.py
Reverse-geocodes a GPS coordinate via Nominatim (OpenStreetMap, free, no key)
and maps the resulting place type to a SceneDescription for Lyria.
"""

import logging
from dataclasses import dataclass

import httpx

from gemini_vision import SceneDescription

logger = logging.getLogger(__name__)

NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
NOMINATIM_HEADERS = {
    "User-Agent": "MusicMap/1.0 (hackathon project)",
    "Accept-Language": "en",
}

# ---------------------------------------------------------------------------
# Place-type → zone colour (returned to the frontend for map rendering)
# ---------------------------------------------------------------------------

ZONE_COLORS = {
    "park":        "#4caf50",   # green
    "nature":      "#66bb6a",   # light green
    "beach":       "#26c6da",   # cyan
    "forest":      "#2e7d32",   # dark green
    "water":       "#1565c0",   # deep blue
    "cafe":        "#ffca28",   # amber
    "restaurant":  "#ff7043",   # deep orange
    "bar":         "#ab47bc",   # purple
    "nightclub":   "#e91e63",   # pink
    "commercial":  "#ff9800",   # orange
    "shopping":    "#ffa726",   # light orange
    "university":  "#42a5f5",   # blue
    "library":     "#5c6bc0",   # indigo
    "school":      "#29b6f6",   # light blue
    "residential": "#8d6e63",   # brown
    "industrial":  "#546e7a",   # blue grey
    "sports":      "#ef5350",   # red
    "stadium":     "#d32f2f",   # dark red
    "hospital":    "#ec407a",   # pink
    "road":        "#bdbdbd",   # grey
    "default":     "#7c6af7",   # accent purple
}

# ---------------------------------------------------------------------------
# Place-type → SceneDescription presets
# ---------------------------------------------------------------------------

_PLACE_SCENES: dict[str, dict] = {
    "park": dict(
        mood="peaceful", energy=0.25, suggested_genre="acoustic guitar, folk",
        suggested_bpm=72, density=0.25, guidance=4.0,
    ),
    "nature": dict(
        mood="calm", energy=0.2, suggested_genre="ambient, nature sounds",
        suggested_bpm=65, density=0.2, guidance=4.0,
    ),
    "beach": dict(
        mood="joyful", energy=0.45, suggested_genre="tropical, chillwave",
        suggested_bpm=88, density=0.4, guidance=3.5,
    ),
    "forest": dict(
        mood="mysterious", energy=0.3, suggested_genre="dark ambient, cinematic",
        suggested_bpm=70, density=0.35, guidance=4.5,
    ),
    "water": dict(
        mood="calm", energy=0.2, suggested_genre="ambient piano, oceanic",
        suggested_bpm=60, density=0.2, guidance=4.0,
    ),
    "cafe": dict(
        mood="calm", energy=0.35, suggested_genre="lo-fi hip hop, jazz",
        suggested_bpm=82, density=0.35, guidance=4.0,
    ),
    "restaurant": dict(
        mood="romantic", energy=0.4, suggested_genre="jazz, bossa nova",
        suggested_bpm=78, density=0.4, guidance=4.0,
    ),
    "bar": dict(
        mood="joyful", energy=0.65, suggested_genre="indie pop, funk",
        suggested_bpm=110, density=0.6, guidance=3.5,
    ),
    "nightclub": dict(
        mood="energetic", energy=0.95, suggested_genre="electronic dance, house",
        suggested_bpm=128, density=0.9, guidance=3.0,
    ),
    "commercial": dict(
        mood="energetic", energy=0.7, suggested_genre="upbeat pop, electronic",
        suggested_bpm=118, density=0.65, guidance=3.5,
    ),
    "shopping": dict(
        mood="joyful", energy=0.6, suggested_genre="pop, upbeat indie",
        suggested_bpm=112, density=0.6, guidance=3.5,
    ),
    "university": dict(
        mood="calm", energy=0.35, suggested_genre="lo-fi beats, focus music",
        suggested_bpm=80, density=0.3, guidance=4.5,
    ),
    "library": dict(
        mood="melancholic", energy=0.2, suggested_genre="minimal piano, ambient",
        suggested_bpm=65, density=0.15, guidance=5.0,
    ),
    "school": dict(
        mood="joyful", energy=0.55, suggested_genre="indie pop, bright acoustic",
        suggested_bpm=100, density=0.5, guidance=4.0,
    ),
    "residential": dict(
        mood="peaceful", energy=0.3, suggested_genre="warm acoustic, singer-songwriter",
        suggested_bpm=75, density=0.3, guidance=4.0,
    ),
    "industrial": dict(
        mood="dark", energy=0.5, suggested_genre="dark techno, minimal",
        suggested_bpm=95, density=0.5, guidance=5.0,
    ),
    "sports": dict(
        mood="energetic", energy=0.85, suggested_genre="high energy electronic, rock",
        suggested_bpm=140, density=0.8, guidance=3.0,
    ),
    "stadium": dict(
        mood="energetic", energy=0.95, suggested_genre="anthemic rock, stadium pop",
        suggested_bpm=135, density=0.85, guidance=3.0,
    ),
    "hospital": dict(
        mood="calm", energy=0.15, suggested_genre="soft ambient, healing",
        suggested_bpm=58, density=0.15, guidance=5.0,
    ),
    "road": dict(
        mood="energetic", energy=0.6, suggested_genre="driving rock, electronic",
        suggested_bpm=110, density=0.55, guidance=3.5,
    ),
    "default": dict(
        mood="calm", energy=0.4, suggested_genre="ambient, neutral",
        suggested_bpm=85, density=0.35, guidance=4.0,
    ),
}


@dataclass
class LocationInfo:
    lat: float
    lon: float
    place_type: str          # key into ZONE_COLORS / _PLACE_SCENES
    display_name: str        # human-readable label for the UI
    zone_color: str          # hex color for the Leaflet circle


def _classify_place(nominatim: dict) -> tuple[str, str]:
    """
    Extract a normalised place_type and display_name from a Nominatim response.
    Returns (place_type, display_name).
    """
    addr = nominatim.get("address", {})
    osm_class = nominatim.get("class", "")
    osm_type = nominatim.get("type", "")

    # Priority order: specific amenity → leisure → landuse → highway → class
    amenity = addr.get("amenity", "")
    leisure = addr.get("leisure", "")
    landuse = addr.get("landuse", "")
    highway = addr.get("highway", "")
    natural = addr.get("natural", "")
    tourism = addr.get("tourism", "")

    place_type = "default"
    label_parts = []

    if amenity in ("cafe", "coffee_shop"):
        place_type = "cafe"
    elif amenity in ("restaurant", "fast_food", "food_court"):
        place_type = "restaurant"
    elif amenity in ("bar", "pub", "biergarten"):
        place_type = "bar"
    elif amenity in ("nightclub", "casino"):
        place_type = "nightclub"
    elif amenity in ("university", "college"):
        place_type = "university"
    elif amenity in ("library",):
        place_type = "library"
    elif amenity in ("school", "kindergarten"):
        place_type = "school"
    elif amenity in ("hospital", "clinic", "pharmacy"):
        place_type = "hospital"
    elif amenity in ("gym", "sports_centre", "swimming_pool"):
        place_type = "sports"
    elif amenity in ("stadium",):
        place_type = "stadium"
    elif leisure in ("park", "garden", "dog_park"):
        place_type = "park"
    elif leisure in ("pitch", "sports_centre", "stadium"):
        place_type = "sports"
    elif leisure in ("beach_resort", "marina"):
        place_type = "beach"
    elif natural in ("beach",):
        place_type = "beach"
    elif natural in ("wood", "forest"):
        place_type = "forest"
    elif natural in ("water", "bay", "lake"):
        place_type = "water"
    elif landuse in ("commercial", "retail"):
        place_type = "commercial"
    elif landuse in ("industrial",):
        place_type = "industrial"
    elif landuse in ("residential",):
        place_type = "residential"
    elif osm_class in ("highway",):
        place_type = "road"
    elif osm_class in ("tourism",) or tourism:
        place_type = "park"  # treat tourist spots like parks

    # Build a friendly display name
    if amenity:
        label_parts.append(amenity.replace("_", " "))
    elif leisure:
        label_parts.append(leisure.replace("_", " "))
    elif landuse:
        label_parts.append(landuse.replace("_", " "))

    for key in ("road", "neighbourhood", "suburb", "city_district", "city", "town", "village"):
        val = addr.get(key)
        if val:
            label_parts.append(val)
            break

    display_name = ", ".join(label_parts) if label_parts else nominatim.get("display_name", "somewhere")[:60]

    return place_type, display_name


async def reverse_geocode(lat: float, lon: float) -> LocationInfo:
    """
    Call Nominatim to reverse-geocode a coordinate.
    Returns a LocationInfo with place_type, display_name, and zone_color.
    """
    params = {"lat": lat, "lon": lon, "format": "jsonv2", "zoom": 17, "addressdetails": 1}

    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(NOMINATIM_URL, params=params, headers=NOMINATIM_HEADERS)
        response.raise_for_status()
        data = response.json()

    place_type, display_name = _classify_place(data)
    zone_color = ZONE_COLORS.get(place_type, ZONE_COLORS["default"])

    return LocationInfo(
        lat=lat,
        lon=lon,
        place_type=place_type,
        display_name=display_name,
        zone_color=zone_color,
    )


def location_to_scene(info: LocationInfo) -> SceneDescription:
    """Convert a LocationInfo into a SceneDescription for Lyria."""
    preset = _PLACE_SCENES.get(info.place_type, _PLACE_SCENES["default"])
    return SceneDescription(
        mood=preset["mood"],
        energy=preset["energy"],
        setting=info.display_name,
        suggested_genre=preset["suggested_genre"],
        suggested_bpm=preset["suggested_bpm"],
        density=preset["density"],
        guidance=preset["guidance"],
    )
