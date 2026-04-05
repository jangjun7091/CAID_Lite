"""PatternSelector: maps a DesignPlan to relevant YAML patterns.

This is a pure-Python component -- no LLM call is made.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from ..logging.logger import get_logger
from .base import DesignPlan

_log = get_logger(__name__)

# Maximum number of patterns to return per selection call.
_MAX_PATTERNS = 3

# Keyword mapping: geometry_type or feature keyword -> pattern name(s).
# Keys are lower-case substrings; values are pattern names (without .yaml).
_KEYWORD_MAP: Dict[str, List[str]] = {
    "plate":       ["plate"],
    "slab":        ["plate"],
    "panel":       ["plate"],
    "box":         ["box"],
    "enclosure":   ["box"],
    "housing":     ["box"],
    "cylinder":    ["cylinder"],
    # Everyday consumer objects
    "phone":       ["rounded_box"],
    "iphone":      ["rounded_box"],
    "smartphone":  ["rounded_box"],
    "tablet":      ["rounded_box"],
    "remote":      ["rounded_box"],
    "rounded":     ["rounded_box"],
    "cup":         ["mug", "hollow_cylinder"],
    "mug":         ["mug", "hollow_cylinder"],
    "tumbler":     ["hollow_cylinder"],
    "bottle":      ["hollow_cylinder"],
    "glass":       ["hollow_cylinder"],
    "container":   ["hollow_cylinder"],
    "can":         ["hollow_cylinder"],
    "vessel":      ["hollow_cylinder"],
    "hollow":      ["hollow_cylinder", "box"],
    "power":       ["power_strip", "box"],
    "strip":       ["power_strip"],
    "outlet":      ["power_strip"],
    "socket":      ["power_strip"],
    "handle":      ["mug"],
    "gear":        ["spur_gear", "cylinder"],
    "spur":        ["spur_gear"],
    "sprocket":    ["spur_gear", "cylinder"],
    "tooth":       ["spur_gear"],
    "teeth":       ["spur_gear"],
    "involute":    ["spur_gear"],
    # Mechanical rotating/stepped parts
    "shaft":       ["shaft", "shaft_support", "cylinder"],
    "axle":        ["shaft", "shaft_support", "cylinder"],
    "spindle":     ["shaft"],
    "keyway":      ["shaft"],
    "shoulder":    ["shaft"],
    # U/C channel brackets
    "u_bracket":   ["u_bracket"],
    "u-bracket":   ["u_bracket"],
    "channel":     ["u_bracket"],
    "c-channel":   ["u_bracket"],
    # Gusset / stiffener
    "gusset":      ["gusset", "l_bracket"],
    "stiffener":   ["gusset"],
    "reinforcement": ["gusset"],
    # Counterbore / countersink
    "counterbore": ["counterbore"],
    "cbore":       ["counterbore"],
    "tube":        ["tube"],
    "pipe":        ["tube"],
    "hole":        ["through_hole"],
    "through":     ["through_hole"],
    "blind":       ["blind_hole"],
    "slot":        ["slot"],
    "pocket":      ["pocket"],
    "boss":        ["boss"],
    "fillet":      ["fillet"],
    "chamfer":     ["chamfer"],
    "bracket":     ["l_bracket", "plate"],
    "mount":       ["mounting_block"],
    "mounting":    ["mounting_block"],
    "bearing":     ["bearing_mount"],
    "flange":      ["flange"],
    "spacer":      ["spacer"],
    "standoff":    ["spacer"],
    "connector":   ["connector_block"],
    "grid":        ["hole_rarray"],
    "rarray":      ["hole_rarray"],
    "pushpoints":  ["hole_pushpoints"],
}


class PatternSelector:
    """Selects up to ``_MAX_PATTERNS`` relevant YAML patterns for a DesignPlan.

    Patterns are loaded lazily from ``patterns_dir`` the first time
    ``select()`` is called and cached for the lifetime of the instance.

    Args:
        patterns_dir: Directory containing ``*.yaml`` pattern files.
                      Defaults to ``config/patterns/`` relative to CWD.

    Example::

        selector = PatternSelector()
        patterns = selector.select(plan)
        # Returns a list of dicts, each with keys from the YAML schema.
    """

    def __init__(self, patterns_dir: Optional[Path] = None) -> None:
        self._patterns_dir = patterns_dir
        self._cache: Optional[Dict[str, Dict[str, Any]]] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def select(self, plan: DesignPlan) -> List[Dict[str, Any]]:
        """Return a list of pattern dicts relevant to *plan*.

        Scoring is purely keyword-based:
          - The ``geometry_type`` field is checked against ``_KEYWORD_MAP``.
          - Each entry in ``plan.features`` is checked against ``_KEYWORD_MAP``.
          - Patterns are deduplicated and trimmed to ``_MAX_PATTERNS``.

        Args:
            plan: DesignPlan from the ArchitectAgent.

        Returns:
            List of pattern dicts (empty if no matches or no patterns loaded).
        """
        library = self._load_library()
        if not library:
            return []

        scored: Dict[str, int] = {}

        def _score(text: str) -> None:
            lower = text.lower()
            for keyword, names in _KEYWORD_MAP.items():
                if keyword in lower:
                    for name in names:
                        scored[name] = scored.get(name, 0) + 1

        _score(plan.geometry_type)
        for feature in plan.features:
            _score(feature)
        _score(plan.notes)

        # Sort by score descending, then alphabetically for determinism
        ordered = sorted(scored.keys(), key=lambda n: (-scored[n], n))
        selected = [library[n] for n in ordered if n in library]
        result = selected[:_MAX_PATTERNS]
        names = [p.get("name", "?") for p in result]
        _log.debug(f"PatternSelector.select: matched {names}")
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_library(self) -> Dict[str, Dict[str, Any]]:
        """Load all *.yaml pattern files, returning a name->dict mapping."""
        if self._cache is not None:
            return self._cache

        import yaml  # pyyaml -- always available

        dirs_to_try: List[Path] = []
        if self._patterns_dir is not None:
            dirs_to_try.append(Path(self._patterns_dir))
        dirs_to_try.append(Path("config") / "patterns")

        library: Dict[str, Dict[str, Any]] = {}
        for d in dirs_to_try:
            if not d.is_dir():
                continue
            for yaml_file in sorted(d.glob("*.yaml")):
                try:
                    data = yaml.safe_load(yaml_file.read_text(encoding="utf-8"))
                    if isinstance(data, dict) and "name" in data:
                        library[data["name"]] = data
                except Exception as exc:  # noqa: BLE001
                    _log.warning(f"PatternSelector: failed to load {yaml_file}: {exc}")
            if library:
                break  # use first directory that has patterns

        self._cache = library
        _log.debug(f"PatternSelector: loaded {len(library)} patterns")
        return library
