"""Lane E — system prompt rendering contract tests (Lane B voice-agent).

Frozen contract (plan LANE B / spec §5):
render_system_prompt(config) must produce:
1. disclosure script verbatim as the FIRST sentence block
2. question_flow rendered with explicit numbering (1., 2., ...)
3. extraction instructions including the never-fabricate rule

Skips with a precise reason until Lane B's renderer module is merged.
"""
from __future__ import annotations

import re
from typing import Any, Callable

import pytest

from _qa_voice_contract import locate_symbols, load_agent_config, normalize
from app.prompting import apply_token_substitution

_RENDERER_CANDIDATE_MODULES: list[str] = [
    "app.prompting",
    "app.prompts",
    "app.prompt_renderer",
    "app.pipeline",
    "app.conversation",
    "agent",
]
RENDERER_ATTRS: list[str] = ["render_system_prompt", "render_system_output"]


@pytest.fixture(scope="module")
def render() -> Callable[..., str]:
    fn, why = locate_symbols(RENDERER_ATTRS, _RENDERER_CANDIDATE_MODULES)
    if fn is None:
        pytest.skip(f"[Lane B] prompt renderer not merged yet: {why}")
    return fn


def _goals_section(prompt: str) -> str:
    """Slice the prompt between the goals header and extraction header.

    Numbered content elsewhere (disclosure scripts, company context) is
    legitimate; question-flow numbering is only asserted within its own block.
    """
    start = prompt.find(QUESTIONS_HEADER_HINT)
    end = prompt.find(EXTRACTION_HEADER_HINT)
    if start == -1:
        return prompt
    return prompt[start : end if end > start else len(prompt)]


QUESTIONS_HEADER_HINT = "YOUR GOALS"
EXTRACTION_HEADER_HINT = "RECORDING ANSWERS"


def _first_question_marker_index(prompt: str) -> int | None:
    """Index of the '1.' goal marker in NORMALIZED full-prompt coordinates,
    comparable with other normalize(prompt) indices (normalize collapses
    newlines, so the marker is matched without line anchors)."""
    norm = normalize(prompt)
    start = norm.find(normalize(QUESTIONS_HEADER_HINT))
    if start == -1:
        return None
    end = norm.find(normalize(EXTRACTION_HEADER_HINT))
    window = norm[start : end if end > start else len(norm)]
    match = re.search(r"\b1\s*[.)]\s", window)
    return start + match.start() if match else None


def test_disclosure_is_the_first_block(render: Callable[..., str]) -> None:
    config = load_agent_config()
    prompt = render(config)
    assert isinstance(prompt, str) and prompt.strip(), "renderer returned an empty prompt"

    disclosure = normalize(apply_token_substitution(config["disclosure_script"]))
    probe = " ".join(disclosure.split()[:8])
    norm_prompt = normalize(prompt)
    disc_idx = norm_prompt.find(probe)
    assert disc_idx >= 0, (
        f"disclosure script missing from prompt. Probe {probe!r} not found in:\n{prompt[:600]!r}"
    )
    q_idx = _first_question_marker_index(prompt)
    if q_idx is None:
        pytest.fail(f"no numbered question marker ('1.') found in prompt:\n{prompt[:600]!r}")
    assert disc_idx < q_idx, (
        f"disclosure must precede the numbered questions "
        f"(disclosure at {disc_idx}, first question marker at {q_idx})"
    )
    preamble = norm_prompt[:disc_idx]
    assert len(preamble) <= 200, (
        f"something precedes the disclosure block ({len(preamble)} chars): {preamble[:200]!r}"
    )


def test_questions_are_numbered_in_order(render: Callable[..., str]) -> None:
    config = load_agent_config()
    prompt = render(config)
    norm_prompt = normalize(prompt)

    positions: list[int] = []
    goals = _goals_section(prompt)
    norm_goals = normalize(goals)
    for step, entry in enumerate(config["question_flow"], start=1):
        marker = re.search(rf"(?m)^\s*{step}\s*[.)]\s", goals)
        assert marker is not None, (
            f"question step {step} has no '{step}.' number marker in:\n{goals[:600]!r}"
        )
        positions.append(marker.start())
        question_text = normalize(
            apply_token_substitution(entry["question"])
        )
        window = norm_goals[marker.start() : marker.start() + 500]
        key_words = " ".join(question_text.split()[:5])
        assert key_words in window, (
            f"question {step} text ({key_words!r}) not found near its marker; "
            f"window was {window[:300]!r}"
        )
    assert positions == sorted(positions), f"questions out of order at {positions}"


def test_never_fabricate_rule_present(render: Callable[..., str]) -> None:
    config = load_agent_config()
    prompt = render(config)
    assert "fabricat" in normalize(prompt), (
        f"never-fabricate extraction rule missing from prompt:\n{prompt[:600]!r}"
    )


def test_render_is_deterministic(render: Callable[..., str]) -> None:
    config = load_agent_config()
    assert render(config) == render(config), "renderer output differs between identical calls"
