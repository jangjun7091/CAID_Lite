"""ISO standard parts dimension tables.

All dimensions are in millimeters.

Categories
----------
fastener : Bolts, nuts, washers (ISO 4762, 7380, 10642, 4026, 4032, 7089)
bearing  : Deep groove ball bearings (ISO 15 / DIN 625)
shaft    : Shafts, set collars, parallel keys
profile  : T-slot aluminum extrusion
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# CATALOG — main dimension database
#
# Each entry:
#   name            : display name
#   category        : "fastener" | "bearing" | "shaft" | "profile"
#   has_length      : True when length (mm) is a required extra parameter
#   default_lengths : suggested lengths when has_length is True
#   sizes           : {label → {dim_key: float, ...}}
# ---------------------------------------------------------------------------

CATALOG: dict = {

    # ────────────────────────────────────────────────────────────────────────
    # FASTENERS
    # ────────────────────────────────────────────────────────────────────────

    "iso4762": {
        "name": "ISO 4762 Socket Head Cap Screw",
        "category": "fastener",
        "has_length": True,
        "default_lengths": [5, 6, 8, 10, 12, 16, 20, 25, 30, 35, 40, 50],
        "sizes": {
            "M2":   {"d": 2.0,  "pitch": 0.4,  "dk": 3.8,  "k": 2.0,  "s": 1.5},
            "M2.5": {"d": 2.5,  "pitch": 0.45, "dk": 4.5,  "k": 2.5,  "s": 2.0},
            "M3":   {"d": 3.0,  "pitch": 0.5,  "dk": 5.5,  "k": 3.0,  "s": 2.5},
            "M4":   {"d": 4.0,  "pitch": 0.7,  "dk": 7.0,  "k": 4.0,  "s": 3.0},
            "M5":   {"d": 5.0,  "pitch": 0.8,  "dk": 8.5,  "k": 5.0,  "s": 4.0},
            "M6":   {"d": 6.0,  "pitch": 1.0,  "dk": 10.0, "k": 6.0,  "s": 5.0},
            "M8":   {"d": 8.0,  "pitch": 1.25, "dk": 13.0, "k": 8.0,  "s": 6.0},
            "M10":  {"d": 10.0, "pitch": 1.5,  "dk": 16.0, "k": 10.0, "s": 8.0},
            "M12":  {"d": 12.0, "pitch": 1.75, "dk": 18.0, "k": 12.0, "s": 10.0},
            "M16":  {"d": 16.0, "pitch": 2.0,  "dk": 24.0, "k": 16.0, "s": 14.0},
            "M20":  {"d": 20.0, "pitch": 2.5,  "dk": 30.0, "k": 20.0, "s": 17.0},
        },
    },

    "iso7380": {
        "name": "ISO 7380 Button Head Socket Screw",
        "category": "fastener",
        "has_length": True,
        "default_lengths": [5, 6, 8, 10, 12, 16, 20, 25, 30],
        "sizes": {
            "M3":  {"d": 3.0,  "pitch": 0.5,  "dk": 5.7,  "k": 1.65, "s": 2.05},
            "M4":  {"d": 4.0,  "pitch": 0.7,  "dk": 7.6,  "k": 2.2,  "s": 2.56},
            "M5":  {"d": 5.0,  "pitch": 0.8,  "dk": 9.5,  "k": 2.75, "s": 3.08},
            "M6":  {"d": 6.0,  "pitch": 1.0,  "dk": 10.5, "k": 3.3,  "s": 4.095},
            "M8":  {"d": 8.0,  "pitch": 1.25, "dk": 14.0, "k": 4.4,  "s": 5.095},
            "M10": {"d": 10.0, "pitch": 1.5,  "dk": 17.5, "k": 5.5,  "s": 6.095},
            "M12": {"d": 12.0, "pitch": 1.75, "dk": 21.0, "k": 6.6,  "s": 8.115},
        },
    },

    "iso10642": {
        "name": "ISO 10642 Countersunk Socket Screw",
        "category": "fastener",
        "has_length": True,
        "default_lengths": [6, 8, 10, 12, 16, 20, 25, 30],
        "sizes": {
            "M3":  {"d": 3.0,  "pitch": 0.5,  "dk": 6.72,  "k": 1.86, "s": 2.05},
            "M4":  {"d": 4.0,  "pitch": 0.7,  "dk": 8.96,  "k": 2.48, "s": 2.55},
            "M5":  {"d": 5.0,  "pitch": 0.8,  "dk": 11.20, "k": 3.10, "s": 3.05},
            "M6":  {"d": 6.0,  "pitch": 1.0,  "dk": 13.44, "k": 3.72, "s": 4.05},
            "M8":  {"d": 8.0,  "pitch": 1.25, "dk": 17.92, "k": 4.96, "s": 5.14},
            "M10": {"d": 10.0, "pitch": 1.5,  "dk": 22.40, "k": 6.20, "s": 6.14},
            "M12": {"d": 12.0, "pitch": 1.75, "dk": 26.88, "k": 7.44, "s": 8.18},
        },
    },

    "iso4026": {
        "name": "ISO 4026 Set Screw (Grub)",
        "category": "fastener",
        "has_length": True,
        "default_lengths": [3, 4, 5, 6, 8, 10, 12, 16, 20],
        "sizes": {
            "M3":  {"d": 3.0,  "pitch": 0.5,  "s": 1.5},
            "M4":  {"d": 4.0,  "pitch": 0.7,  "s": 2.0},
            "M5":  {"d": 5.0,  "pitch": 0.8,  "s": 2.5},
            "M6":  {"d": 6.0,  "pitch": 1.0,  "s": 3.0},
            "M8":  {"d": 8.0,  "pitch": 1.25, "s": 4.0},
            "M10": {"d": 10.0, "pitch": 1.5,  "s": 5.0},
            "M12": {"d": 12.0, "pitch": 1.75, "s": 6.0},
        },
    },

    "iso4032": {
        "name": "ISO 4032 Hex Nut",
        "category": "fastener",
        "has_length": False,
        "default_lengths": [],
        "sizes": {
            "M2":   {"d": 2.0,  "pitch": 0.4,  "s": 4.0,  "m": 1.6},
            "M2.5": {"d": 2.5,  "pitch": 0.45, "s": 5.0,  "m": 2.0},
            "M3":   {"d": 3.0,  "pitch": 0.5,  "s": 5.5,  "m": 2.4},
            "M4":   {"d": 4.0,  "pitch": 0.7,  "s": 7.0,  "m": 3.2},
            "M5":   {"d": 5.0,  "pitch": 0.8,  "s": 8.0,  "m": 4.7},
            "M6":   {"d": 6.0,  "pitch": 1.0,  "s": 10.0, "m": 5.2},
            "M8":   {"d": 8.0,  "pitch": 1.25, "s": 13.0, "m": 6.8},
            "M10":  {"d": 10.0, "pitch": 1.5,  "s": 16.0, "m": 8.4},
            "M12":  {"d": 12.0, "pitch": 1.75, "s": 18.0, "m": 10.8},
            "M16":  {"d": 16.0, "pitch": 2.0,  "s": 24.0, "m": 14.8},
            "M20":  {"d": 20.0, "pitch": 2.5,  "s": 30.0, "m": 18.0},
        },
    },

    "iso7089": {
        "name": "ISO 7089 Plain Washer",
        "category": "fastener",
        "has_length": False,
        "default_lengths": [],
        "sizes": {
            "M2":   {"d1": 2.2,  "d2": 5.0,  "t": 0.3},
            "M2.5": {"d1": 2.7,  "d2": 6.0,  "t": 0.5},
            "M3":   {"d1": 3.2,  "d2": 7.0,  "t": 0.5},
            "M4":   {"d1": 4.3,  "d2": 9.0,  "t": 0.8},
            "M5":   {"d1": 5.3,  "d2": 10.0, "t": 1.0},
            "M6":   {"d1": 6.4,  "d2": 12.0, "t": 1.6},
            "M8":   {"d1": 8.4,  "d2": 16.0, "t": 1.6},
            "M10":  {"d1": 10.5, "d2": 20.0, "t": 2.0},
            "M12":  {"d1": 13.0, "d2": 24.0, "t": 2.5},
            "M16":  {"d1": 17.0, "d2": 30.0, "t": 3.0},
            "M20":  {"d1": 21.0, "d2": 37.0, "t": 3.0},
        },
    },

    # ────────────────────────────────────────────────────────────────────────
    # BEARINGS (ISO 15 / DIN 625)
    # ────────────────────────────────────────────────────────────────────────

    "iso15_6000": {
        "name": "Ball Bearing 6000 Series",
        "category": "bearing",
        "has_length": False,
        "default_lengths": [],
        "sizes": {
            "6000": {"d": 10.0, "D": 26.0, "B": 8.0},
            "6001": {"d": 12.0, "D": 28.0, "B": 8.0},
            "6002": {"d": 15.0, "D": 32.0, "B": 9.0},
            "6003": {"d": 17.0, "D": 35.0, "B": 10.0},
            "6004": {"d": 20.0, "D": 42.0, "B": 12.0},
            "6005": {"d": 25.0, "D": 47.0, "B": 12.0},
            "6006": {"d": 30.0, "D": 55.0, "B": 13.0},
            "6007": {"d": 35.0, "D": 62.0, "B": 14.0},
            "6008": {"d": 40.0, "D": 68.0, "B": 15.0},
            "6009": {"d": 45.0, "D": 75.0, "B": 16.0},
            "6010": {"d": 50.0, "D": 80.0, "B": 16.0},
        },
    },

    "iso15_6200": {
        "name": "Ball Bearing 6200 Series",
        "category": "bearing",
        "has_length": False,
        "default_lengths": [],
        "sizes": {
            "6200": {"d": 10.0, "D": 30.0, "B": 9.0},
            "6201": {"d": 12.0, "D": 32.0, "B": 10.0},
            "6202": {"d": 15.0, "D": 35.0, "B": 11.0},
            "6203": {"d": 17.0, "D": 40.0, "B": 12.0},
            "6204": {"d": 20.0, "D": 47.0, "B": 14.0},
            "6205": {"d": 25.0, "D": 52.0, "B": 15.0},
            "6206": {"d": 30.0, "D": 62.0, "B": 16.0},
            "6207": {"d": 35.0, "D": 72.0, "B": 17.0},
            "6208": {"d": 40.0, "D": 80.0, "B": 15.0},
            "6209": {"d": 45.0, "D": 85.0, "B": 19.0},
            "6210": {"d": 50.0, "D": 90.0, "B": 20.0},
        },
    },

    # ────────────────────────────────────────────────────────────────────────
    # SHAFTS, COLLARS, KEYS
    # ────────────────────────────────────────────────────────────────────────

    "shaft_h6": {
        "name": "Shaft (h6 tolerance)",
        "category": "shaft",
        "has_length": True,
        "default_lengths": [20, 30, 50, 75, 100, 150, 200, 300],
        "sizes": {
            "Ø6":  {"d": 6.0},
            "Ø8":  {"d": 8.0},
            "Ø10": {"d": 10.0},
            "Ø12": {"d": 12.0},
            "Ø15": {"d": 15.0},
            "Ø16": {"d": 16.0},
            "Ø20": {"d": 20.0},
            "Ø25": {"d": 25.0},
            "Ø30": {"d": 30.0},
        },
    },

    "din705": {
        "name": "Set Collar (DIN 705)",
        "category": "shaft",
        "has_length": False,
        "default_lengths": [],
        "sizes": {
            "Ø6":  {"d": 6.0,  "D": 12.0, "B": 8.0},
            "Ø8":  {"d": 8.0,  "D": 16.0, "B": 8.0},
            "Ø10": {"d": 10.0, "D": 20.0, "B": 10.0},
            "Ø12": {"d": 12.0, "D": 22.0, "B": 12.0},
            "Ø16": {"d": 16.0, "D": 28.0, "B": 12.0},
            "Ø20": {"d": 20.0, "D": 32.0, "B": 14.0},
            "Ø25": {"d": 25.0, "D": 40.0, "B": 16.0},
            "Ø30": {"d": 30.0, "D": 45.0, "B": 16.0},
        },
    },

    "din6885": {
        "name": "Parallel Key (DIN 6885)",
        "category": "shaft",
        "has_length": True,
        "default_lengths": [8, 10, 12, 16, 20, 25, 30, 40, 50],
        "sizes": {
            "2×2":   {"b": 2.0,  "h": 2.0},
            "3×3":   {"b": 3.0,  "h": 3.0},
            "4×4":   {"b": 4.0,  "h": 4.0},
            "5×5":   {"b": 5.0,  "h": 5.0},
            "6×6":   {"b": 6.0,  "h": 6.0},
            "8×7":   {"b": 8.0,  "h": 7.0},
            "10×8":  {"b": 10.0, "h": 8.0},
            "12×8":  {"b": 12.0, "h": 8.0},
            "16×10": {"b": 16.0, "h": 10.0},
            "20×12": {"b": 20.0, "h": 12.0},
        },
    },

    # ────────────────────────────────────────────────────────────────────────
    # PROFILES
    # ────────────────────────────────────────────────────────────────────────

    "tslot": {
        "name": "T-Slot Aluminum Profile",
        "category": "profile",
        "has_length": True,
        "default_lengths": [100, 200, 300, 500, 750, 1000],
        "sizes": {
            "2020": {"w": 20.0, "slot_w": 6.0, "slot_d": 6.0, "center_d": 5.0},
            "3030": {"w": 30.0, "slot_w": 8.2, "slot_d": 9.0, "center_d": 6.8},
            "4040": {"w": 40.0, "slot_w": 8.0, "slot_d": 12.0, "center_d": 6.8},
        },
    },
}


# ---------------------------------------------------------------------------
# Category metadata (for UI rendering)
# ---------------------------------------------------------------------------

CATEGORY_META: dict = {
    "fastener": {"label": "Fasteners",    "label_kr": "체결부품"},
    "bearing":  {"label": "Bearings",     "label_kr": "베어링"},
    "shaft":    {"label": "Shaft & Keys", "label_kr": "샤프트/키"},
    "profile":  {"label": "Profiles",     "label_kr": "프로파일"},
}


def get_catalog_by_category() -> dict:
    """Return catalog grouped by category for the API response.

    Returns:
        Dict with one key per category.  Each value is a list of part-type
        dicts: ``id``, ``name``, ``has_length``, ``default_lengths``,
        ``sizes`` (list of labels), ``dims`` (label → dim dict).
    """
    grouped: dict = {cat: [] for cat in CATEGORY_META}
    for part_id, info in CATALOG.items():
        cat = info["category"]
        if cat not in grouped:
            continue
        grouped[cat].append(
            {
                "id": part_id,
                "name": info["name"],
                "has_length": info["has_length"],
                "default_lengths": info.get("default_lengths", []),
                "sizes": list(info["sizes"].keys()),
                "dims": info["sizes"],
            }
        )
    return grouped
