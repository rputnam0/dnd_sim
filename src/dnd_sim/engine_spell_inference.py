from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

_MULTI_TARGET_COUNT_TOKEN_RE = (
    r"(?:[1-9]\d*|one|two|three|four|five|six|seven|eight|nine|ten|"
    r"eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty)"
)
_MULTI_TARGET_QUALIFIER_GAP_RE = r"(?:\s+(?:[a-z][a-z'-]*[,;:]?)){0,4}"
_MULTI_TARGET_NOUN_RE = r"(?:creatures|targets)"
_MULTI_TARGET_DESCRIPTION_RE = re.compile(
    r"\b(?:"
    + rf"up to\s+{_MULTI_TARGET_COUNT_TOKEN_RE}{_MULTI_TARGET_QUALIFIER_GAP_RE}\s+{_MULTI_TARGET_NOUN_RE}"
    + rf"|any\s+number\s+of{_MULTI_TARGET_QUALIFIER_GAP_RE}\s+{_MULTI_TARGET_NOUN_RE}"
    + rf"|one\s+or\s+more{_MULTI_TARGET_QUALIFIER_GAP_RE}\s+{_MULTI_TARGET_NOUN_RE}"
    + rf"|one\s+or\s+two{_MULTI_TARGET_QUALIFIER_GAP_RE}\s+{_MULTI_TARGET_NOUN_RE}"
    + rf"|two\s+or\s+more{_MULTI_TARGET_QUALIFIER_GAP_RE}\s+{_MULTI_TARGET_NOUN_RE}"
    + rf"|{_MULTI_TARGET_COUNT_TOKEN_RE}{_MULTI_TARGET_QUALIFIER_GAP_RE}\s+{_MULTI_TARGET_NOUN_RE}"
    + r")\b",
    flags=re.IGNORECASE,
)
_AREA_DESCRIPTION_HINTS = (
    "each creature",
    "creatures within",
    "radius",
    "cone",
    "cube",
    "cylinder",
    "line",
    "sphere",
    "point you choose",
)
_SINGLE_TARGET_CONDITIONS = (
    "blinded",
    "charmed",
    "deafened",
    "frightened",
    "grappled",
    "incapacitated",
    "invisible",
    "paralyzed",
    "petrified",
    "poisoned",
    "prone",
    "restrained",
    "stunned",
    "unconscious",
)
_SINGLE_TARGET_CONDITION_RE = re.compile(
    r"\b(?:be|is|becomes|become)\s+(" + "|".join(_SINGLE_TARGET_CONDITIONS) + r")\b",
    flags=re.IGNORECASE,
)
_ALLY_MULTI_TARGET_HINTS = (
    "willing creature",
    "willing creatures",
    "friendly creature",
    "friendly creatures",
    "allies",
    "injured creature",
    "injured creatures",
)
_SPELL_TEXT_DASH_RE = re.compile(r"[\u00ad\u2010\u2011\u2012\u2013\u2014\u2212]")
_AOE_TEMPLATE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("line", re.compile(r"\bline\s+(?P<size>\d+)\s*feet?\s*long\b", flags=re.IGNORECASE)),
    ("line", re.compile(r"\b(?P<size>\d+)\s*-\s*foot-long\s+line\b", flags=re.IGNORECASE)),
    ("sphere", re.compile(r"\b(?P<size>\d+)\s*-\s*foot-radius\s+sphere\b", flags=re.IGNORECASE)),
    ("sphere", re.compile(r"\b(?P<size>\d+)\s*-\s*foot\s+sphere\b", flags=re.IGNORECASE)),
    ("cone", re.compile(r"\b(?P<size>\d+)\s*-\s*foot\s+cone\b", flags=re.IGNORECASE)),
    (
        "cylinder",
        re.compile(
            r"\b(?P<size>\d+)\s*-\s*foot-radius(?:[^.]{0,80})\bcylinder\b",
            flags=re.IGNORECASE,
        ),
    ),
    ("cube", re.compile(r"\b(?P<size>\d+)\s*-\s*foot\s+cube\b", flags=re.IGNORECASE)),
    ("line", re.compile(r"\b(?P<size>\d+)\s*-\s*foot\s+line\b", flags=re.IGNORECASE)),
)
_AREA_SELF_ORIGIN_HINTS = (
    "centered on you",
    "around you",
    "radiates from you",
    "emanates from you",
    "from you",
)


def normalize_spell_inference_text(text: str) -> str:
    normalized = str(text or "").lower().replace("’", "'")
    normalized = _SPELL_TEXT_DASH_RE.sub("-", normalized)
    normalized = re.sub(r"\s*-\s*", "-", normalized)
    normalized = re.sub(r"-{2,}", "-", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def is_self_range_text(range_text: str) -> bool:
    return normalize_spell_inference_text(range_text).startswith("self")


def infer_area_template_from_description(
    *,
    description: str,
) -> tuple[str | None, int | None]:
    normalized = normalize_spell_inference_text(description)
    if not normalized:
        return None, None
    has_area_targeting_phrase = any(
        marker in normalized
        for marker in (
            "each creature in",
            "creature in the",
            "creatures in the",
            "targets in the",
        )
    )
    if not has_area_targeting_phrase:
        return None, None
    for aoe_type, pattern in _AOE_TEMPLATE_PATTERNS:
        match = pattern.search(normalized)
        if not match:
            continue
        try:
            size = int(match.group("size"))
        except (TypeError, ValueError):
            continue
        if size <= 0:
            continue
        return aoe_type, size
    return None, None


def area_template_uses_self_origin(
    *,
    aoe_type: str,
    range_text: str,
    description: str,
) -> bool:
    if aoe_type in {"line", "cone"}:
        return False
    if is_self_range_text(range_text):
        return True
    normalized_description = normalize_spell_inference_text(description)
    return any(marker in normalized_description for marker in _AREA_SELF_ORIGIN_HINTS)


def parse_sheet_spell_range_ft(range_text: str) -> int | None:
    normalized = normalize_spell_inference_text(range_text)
    if not normalized:
        return None
    if normalized.startswith("self"):
        return 0
    if "touch" in normalized:
        return 5

    range_match = re.search(r"(\d+)\s*(?:-| )?\s*ft\b", normalized)
    if range_match:
        return int(range_match.group(1))
    feet_match = re.search(r"(\d+)\s*(?:-| )?\s*feet\b", normalized)
    if feet_match:
        return int(feet_match.group(1))
    return None


def description_is_probably_non_single_target(description: str) -> bool:
    normalized = str(description or "")
    if not normalized:
        return False
    if _MULTI_TARGET_DESCRIPTION_RE.search(normalized):
        return True
    normalized = normalized.lower()
    return any(hint in normalized for hint in _AREA_DESCRIPTION_HINTS)


def infer_multi_target_mode_from_description(*, action_type: str, description: str) -> str:
    normalized = str(description or "").lower()
    if any(marker in normalized for marker in _ALLY_MULTI_TARGET_HINTS):
        return "all_allies"
    if action_type in {"attack", "save"}:
        return "all_enemies"
    return "all_creatures"


def _condition_phrase_is_negated(*, description: str, match_start: int) -> bool:
    prefix = str(description[:match_start]).lower().replace("’", "'")
    return bool(re.search(r"(?:can't|cannot|can not|not|never)\s*$", prefix))


def single_target_condition_from_description(description: str) -> str | None:
    text = str(description or "")
    for match in _SINGLE_TARGET_CONDITION_RE.finditer(text):
        if _condition_phrase_is_negated(description=text, match_start=match.start()):
            continue
        return str(match.group(1)).lower()
    return None


def single_target_condition_apply_on(action_type: str) -> str:
    if action_type == "save":
        return "save_fail"
    if action_type == "attack":
        return "hit"
    return "always"


def has_apply_condition_effect(
    mechanics: list[Any],
    *,
    condition: str,
) -> bool:
    for row in mechanics:
        if not isinstance(row, dict):
            continue
        if str(row.get("effect_type", "")).strip().lower() != "apply_condition":
            continue
        if str(row.get("condition", "")).strip().lower() == condition:
            return True
    return False
