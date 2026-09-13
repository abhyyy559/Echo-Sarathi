"""qa-eval harness: orchestrate test calls, validate extraction, measure latency.

Usage (standalone):
    from qa_eval.harness import QAEvalHarness
    harness = QAEvalHarness(backend_url="http://localhost:8000", api_token="...")
    result = await harness.run_eval(agent_version_id=1, to_number="+917842594002")
    print(result.report())

Usage (pytest):
    See tests/test_qa_eval.py for the pytest integration.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger("qa_eval.harness")


@dataclass
class ExpectedField:
    """One field we expect the agent to extract."""
    field_name: str
    expected_value: str
    required: bool = True


@dataclass
class EvalCase:
    """A single evaluation scenario."""
    name: str
    agent_version_id: int
    to_number: str
    expected_fields: list[ExpectedField] = field(default_factory=list)
    max_duration_s: float = 120.0
    # Transcript simulation for offline mode (no live telephony)
    simulated_transcript: list[dict[str, str]] | None = None


@dataclass
class ExtractionResult:
    """Actual extraction from a completed call."""
    field_name: str
    actual_value: str
    confidence: float
    matched: bool = False
    expected_value: str = ""


@dataclass
class LatencyMetrics:
    """Aggregated latency for one call."""
    stt_final_ms: list[float] = field(default_factory=list)
    llm_first_token_ms: list[float] = field(default_factory=list)
    tts_first_audio_ms: list[float] = field(default_factory=list)
    e2e_ms: list[float] = field(default_factory=list)

    @property
    def stt_p50(self) -> float | None:
        return _percentile(self.stt_final_ms, 0.5)

    @property
    def llm_p50(self) -> float | None:
        return _percentile(self.llm_first_token_ms, 0.5)

    @property
    def tts_p50(self) -> float | None:
        return _percentile(self.tts_first_audio_ms, 0.5)

    @property
    def e2e_p50(self) -> float | None:
        return _percentile(self.e2e_ms, 0.5)

    def summary(self) -> dict[str, Any]:
        return {
            "stt_p50_ms": self.stt_p50,
            "llm_p50_ms": self.llm_p50,
            "tts_p50_ms": self.tts_p50,
            "e2e_p50_ms": self.e2e_p50,
            "turns": len(self.stt_final_ms),
        }


@dataclass
class EvalResult:
    """Result of one evaluation case."""
    case_name: str
    status: str  # "pass", "fail", "error", "timeout"
    extractions: list[ExtractionResult] = field(default_factory=list)
    latency: LatencyMetrics = field(default_factory=LatencyMetrics)
    call_id: str | None = None
    duration_s: float = 0.0
    error: str | None = None
    transcript: list[dict[str, str]] = field(default_factory=list)

    @property
    def extraction_accuracy(self) -> float:
        if not self.extractions:
            return 0.0
        matched = sum(1 for e in self.extractions if e.matched)
        return matched / len(self.extractions)

    def report(self) -> str:
        lines = [
            f"=== Eval: {self.case_name} ===",
            f"Status: {self.status}",
            f"Extraction accuracy: {self.extraction_accuracy:.0%} ({sum(1 for e in self.extractions if e.matched)}/{len(self.extractions)})",
        ]
        for e in self.extractions:
            mark = "PASS" if e.matched else "FAIL"
            lines.append(f"  [{mark}] {e.field_name}: expected={e.expected_value!r} actual={e.actual_value!r} conf={e.confidence:.2f}")
        lat = self.latency.summary()
        if lat["turns"]:
            lines.append(f"Latency p50: STT={lat['stt_p50_ms']:.0f}ms LLM={lat['llm_p50_ms']:.0f}ms TTS={lat['tts_p50_ms']:.0f}ms E2E={lat['e2e_p50_ms']:.0f}ms ({lat['turns']} turns)")
        if self.error:
            lines.append(f"Error: {self.error}")
        return "\n".join(lines)


def _percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    idx = int(len(s) * p)
    return s[min(idx, len(s) - 1)]


class QAEvalHarness:
    """Orchestrate evaluation calls against the VocalIQ backend."""

    def __init__(
        self,
        backend_url: str = "http://localhost:8000",
        api_token: str = "",
        timeout_s: float = 180.0,
    ) -> None:
        self._url = backend_url.rstrip("/")
        self._token = api_token
        self._timeout_s = timeout_s

    async def run_eval(self, case: EvalCase) -> EvalResult:
        """Run a single eval case. Uses simulated transcript if provided, else live call."""
        if case.simulated_transcript is not None:
            return self._run_simulated(case)
        return await self._run_live(case)

    def _run_simulated(self, case: EvalCase) -> EvalResult:
        """Offline eval: validate extraction against simulated transcript."""
        t0 = time.monotonic()
        transcript = case.simulated_transcript or []
        extractions = self._extract_from_transcript(transcript, case.expected_fields)
        duration = time.monotonic() - t0

        all_matched = all(e.matched for e in extractions) if extractions else False
        status = "pass" if all_matched and extractions else "fail"

        return EvalResult(
            case_name=case.name,
            status=status,
            extractions=extractions,
            latency=LatencyMetrics(),
            duration_s=duration,
            transcript=transcript,
        )

    async def _run_live(self, case: EvalCase) -> EvalResult:
        """Live eval: place a real call via the backend API and poll for completion."""
        import aiohttp

        t0 = time.monotonic()
        try:
            async with aiohttp.ClientSession() as session:
                # Place the test call
                headers = {"Authorization": f"Bearer {self._token}"}
                payload = {"version_id": case.agent_version_id, "to_number": case.to_number}
                async with session.post(
                    f"{self._url}/api/test-call",
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status != 200:
                        text = await resp.text()
                        return EvalResult(
                            case_name=case.name, status="error",
                            error=f"HTTP {resp.status}: {text}",
                        )
                    data = await resp.json()
                    call_id = data.get("call_id")
                    room_name = data.get("room_name")

                # Poll for call completion
                deadline = t0 + case.max_duration_s
                while time.monotonic() < deadline:
                    await _async_sleep(3.0)
                    async with session.get(
                        f"{self._url}/api/calls/{call_id}",
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=10),
                    ) as resp:
                        if resp.status != 200:
                            continue
                        call_data = await resp.json()
                        status = call_data.get("status", "")
                        if status in ("completed", "error", "no_answer", "busy"):
                            break

                duration = time.monotonic() - t0

                # Fetch transcript + extracted fields
                extractions, transcript, latency = await self._fetch_call_details(
                    session, headers, call_id
                )

                # Validate against expected
                matched_extractions = self._match_extractions(extractions, case.expected_fields)

                return EvalResult(
                    case_name=case.name,
                    status="pass" if all(e.matched for e in matched_extractions) else "fail",
                    extractions=matched_extractions,
                    latency=latency,
                    call_id=call_id,
                    duration_s=duration,
                    transcript=transcript,
                )
        except Exception as exc:
            return EvalResult(
                case_name=case.name, status="error",
                error=str(exc), duration_s=time.monotonic() - t0,
            )

    async def _fetch_call_details(
        self, session: Any, headers: dict, call_id: str
    ) -> tuple[list[dict], list[dict], LatencyMetrics]:
        """Fetch transcript turns and extracted fields for a completed call."""
        extractions: list[dict] = []
        transcript: list[dict[str, str]] = []
        latency = LatencyMetrics()

        async with session.get(
            f"{self._url}/api/calls/{call_id}/extracted-fields",
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                extractions = data if isinstance(data, list) else data.get("fields", [])

        async with session.get(
            f"{self._url}/api/calls/{call_id}/transcript",
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                turns = data if isinstance(data, list) else data.get("turns", [])
                for turn in turns:
                    transcript.append({
                        "speaker": turn.get("speaker", ""),
                        "text": turn.get("text", ""),
                    })
                    # Collect latency
                    if turn.get("stt_final_ms"):
                        latency.stt_final_ms.append(float(turn["stt_final_ms"]))
                    if turn.get("llm_first_token_ms"):
                        latency.llm_first_token_ms.append(float(turn["llm_first_token_ms"]))
                    if turn.get("tts_first_audio_ms"):
                        latency.tts_first_audio_ms.append(float(turn["tts_first_audio_ms"]))
                    if turn.get("e2e_ms"):
                        latency.e2e_ms.append(float(turn["e2e_ms"]))

        return extractions, transcript, latency

    def _extract_from_transcript(
        self, transcript: list[dict[str, str]], expected: list[ExpectedField]
    ) -> list[ExtractionResult]:
        """Simulate extraction validation from a pre-recorded transcript."""
        results = []
        for exp in expected:
            # Heuristic: expected value appears in any turn (agent or caller).
            found = False
            actual = ""
            needle = exp.expected_value.lower()
            for turn in transcript:
                text = turn.get("text", "").lower()
                if needle in text:
                    found = True
                    actual = exp.expected_value
                    break
            results.append(ExtractionResult(
                field_name=exp.field_name,
                expected_value=exp.expected_value,
                actual_value=actual if found else "",
                confidence=0.9 if found else 0.0,
                matched=found,
            ))
        return results

    def _match_extractions(
        self, actual: list[dict], expected: list[ExpectedField]
    ) -> list[ExtractionResult]:
        """Match actual extractions against expected fields."""
        results = []
        actual_map = {e.get("field_name", ""): e for e in actual}
        for exp in expected:
            entry = actual_map.get(exp.field_name)
            if entry is None:
                results.append(ExtractionResult(
                    field_name=exp.field_name, expected_value=exp.expected_value,
                    actual_value="", confidence=0.0, matched=False,
                ))
                continue
            actual_val = str(entry.get("field_value", entry.get("value", "")))
            confidence = float(entry.get("confidence", 0.0))
            # Fuzzy match: exact or substring
            matched = (
                exp.expected_value.lower() == actual_val.lower()
                or exp.expected_value.lower() in actual_val.lower()
                or actual_val.lower() in exp.expected_value.lower()
            )
            results.append(ExtractionResult(
                field_name=exp.field_name,
                expected_value=exp.expected_value,
                actual_value=actual_val,
                confidence=confidence,
                matched=matched,
            ))
        return results


async def _async_sleep(seconds: float) -> None:
    import asyncio
    await asyncio.sleep(seconds)
