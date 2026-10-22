"""Bracket-token substitution ported from voice-agent/app/prompting.py.

Keep the two in sync: KNOWN_TOKENS here must cover the same placeholder
names the voice worker understands, plus the lead-gen aliases presets use
([Lead Name], [Company Name], [Agent Name]).
"""
from __future__ import annotations

import re
from typing import Any, Mapping, Optional

KNOWN_TOKENS: tuple[str, ...] = (
    "[Institution Name]",
    "[Company Name]",
    "[Student Name]",
    "[Lead Name]",
    "[Parent/Guardian Name]",
    "[Agent Name]",
    "[Expected Return Date]",
)

_BRACKET_ARTIFACT_RE = re.compile(r"\[[^\]]*\]")
_DOUBLE_SPACE_RE = re.compile(r"\s{2,}")

_NAME_KEYS = ("student_name", "name", "contact_name", "full_name", "lead_name")
_PARENT_KEYS = ("parent_name", "parent", "guardian", "contact_person")


def is_bracket_placeholder(value: Any) -> bool:
    """True for an unfilled template token such as ``[Institution Name]``.

    Presets ship bracket tokens for a tenant to fill in. One stored verbatim in
    ``company_context`` is NOT a name: it used to win the institution lookup and
    reach the call, where the worker strips the brackets and the caller hears a
    hole ("I am from ." / "నేను నుండి AI అసిస్టెంట్").
    """
    text = str(value or "").strip()
    return text.startswith("[") and text.endswith("]") and len(text) > 2


def _first(contact: Mapping[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = str(contact.get(key) or "").strip()
        if value:
            return value
    return ""


def build_token_map(
    contact: Optional[Mapping[str, Any]] = None,
    institution: str = "",
    agent_name: str = "",
) -> dict[str, str]:
    """Resolve known placeholder tokens to real values for this call."""
    card = contact if isinstance(contact, Mapping) else {}
    name = _first(card, _NAME_KEYS)
    parent = _first(card, _PARENT_KEYS)
    org = str(institution or "").strip()
    who = str(agent_name or "").strip() or "an AI assistant"
    return {
        "[Institution Name]": org,
        "[Company Name]": org,
        "[Student Name]": name,
        "[Lead Name]": name,
        "[Parent/Guardian Name]": parent,
        "[Agent Name]": who,
        "[Expected Return Date]": "",
    }


def apply_token_substitution(
    text: str, tokens: Optional[Mapping[str, str]] = None
) -> str:
    """Replace known bracket tokens; empties removed, leftovers stripped."""
    if not text:
        return text
    out = str(text)
    for token, value in (tokens or {}).items():
        out = out.replace(str(token), str(value) if value is not None else "")
    out = _BRACKET_ARTIFACT_RE.sub("", out)
    return _DOUBLE_SPACE_RE.sub(" ", out).strip()
