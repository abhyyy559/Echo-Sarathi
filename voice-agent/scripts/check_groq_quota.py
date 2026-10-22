r"""Verify the Groq key-pool quota assumption before a campaign.

Measured 2026-10-20 with the five project keys:

* Request counters are PER KEY: all five keys showed different
  ``x-ratelimit-remaining-requests`` values, so the pool really has
  5,000 requests/day.
* The TOKEN bucket is SHARED: one 5,012-token request on key #1 dropped key
  #2's remaining tokens from 7,986 to 3,098. Groq's published free-plan limits
  are 8,000 TPM and 200,000 TPD per model, applied at the organization level,
  not 40K/1M. Cached prompt tokens do not count, so the real per-call cost
  depends on cache hits.
* Request capacity (5,000/day across the per-key/project counters) is NOT the
  binding limit: budget against 200K TPD. At ~7K counted tokens/call that is
  ~28 calls/day; at ~1.4K it is ~140. Measure real usage before promising a
  daily call volume.

So the five keys expand RPM/RPD but NOT token throughput. A TPM 429 must skip
the whole Groq tier; an RPD/RPM 429 only benches the current key.

Usage (from the repo root; the voice-agent venv has httpx + dotenv):

    voice-agent\.venv\Scripts\python.exe voice-agent\scripts\check_groq_quota.py
    voice-agent\.venv\Scripts\python.exe voice-agent\scripts\check_groq_quota.py --requests 40
    voice-agent\.venv\Scripts\python.exe voice-agent\scripts\check_groq_quota.py --tpm-probe

``--tpm-probe`` consumes about 5K tokens and depletes the shared bucket for
about a minute: do not run it immediately before a demo.

The script NEVER prints a key. It exits 0 even when 429s are observed: the
point is to document the real cap, not to fail the build.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_MODEL = "qwen/qwen3.8-27b"
# Headers worth reporting. Groq uses x-ratelimit-* on chat completions.
_RATE_HEADERS = (
    "x-ratelimit-limit-requests",
    "x-ratelimit-remaining-requests",
    "x-ratelimit-reset-requests",
    "x-ratelimit-limit-tokens",
    "x-ratelimit-remaining-tokens",
    "x-ratelimit-reset-tokens",
    "retry-after",
)


def _load_keys() -> list[str]:
    load_dotenv(REPO_ROOT / ".env")
    raw = f"{os.getenv('GROQ_API_KEY', '')},{os.getenv('GROQ_API_KEYS', '')}"
    keys: list[str] = []
    for part in raw.split(","):
        key = part.strip()
        if key and key not in keys:
            keys.append(key)
    return keys


def _header(resp: httpx.Response, name: str) -> str:
    value = resp.headers.get(name, "")
    return str(value).strip() or "-"


def _mask(index: int) -> str:
    return f"key#{index + 1}"


async def _one_request(
    client: httpx.AsyncClient,
    *,
    base_url: str,
    model: str,
    key: str,
) -> dict[str, str | int]:
    body = {
        "model": model,
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 1,
        "temperature": 0,
        "stream": False,
    }
    try:
        resp = await client.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json=body,
        )
    except Exception as exc:  # noqa: BLE001 - report transport failures too
        return {"status": 0, "error": type(exc).__name__, **{h: "-" for h in _RATE_HEADERS}}
    out: dict[str, str | int] = {"status": resp.status_code, "error": ""}
    for header in _RATE_HEADERS:
        out[header] = _header(resp, header)
    return out


async def _run_tpm_probe(
    client: httpx.AsyncClient,
    keys: list[str],
    args: argparse.Namespace,
) -> int:
    """Prove whether the token bucket is per key or shared.

    Sends a tiny request on key #1 and key #2 to read their baselines, burns
    ~5K tokens on key #1, then reads key #2 again. If key #2's remaining
    tokens collapse too, the bucket is shared.
    """
    if len(keys) < 2:
        print("TPM probe needs at least two keys.", file=sys.stderr)
        return 2
    base = f"{args.base_url.rstrip('/')}/chat/completions"

    async def tiny(key: str) -> httpx.Response:
        return await client.post(
            base,
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": args.model,
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 1,
                "temperature": 0,
            },
        )

    first = await tiny(keys[0])
    second = await tiny(keys[1])
    before_first = _header(first, "x-ratelimit-remaining-tokens")
    before_second = _header(second, "x-ratelimit-remaining-tokens")
    print(f"key#1 baseline: status={first.status_code} remaining_tokens={before_first}")
    print(f"key#2 baseline: status={second.status_code} remaining_tokens={before_second}")

    # ~5K tokens (measured 5,012 with this text).
    big_text = "The quick brown fox jumps over the lazy dog. " * 500
    big = await client.post(
        base,
        headers={"Authorization": f"Bearer {keys[0]}"},
        json={
            "model": args.model,
            "messages": [{"role": "user", "content": big_text}],
            "max_tokens": 1,
            "temperature": 0,
        },
    )
    prompt_tokens = ""
    try:
        prompt_tokens = str(big.json().get("usage", {}).get("prompt_tokens", ""))
    except Exception:  # noqa: BLE001 - non-JSON error body
        pass
    print(
        f"key#1 big request: status={big.status_code} prompt_tokens={prompt_tokens or '?'} "
        f"remaining_tokens={_header(big, 'x-ratelimit-remaining-tokens')}"
    )
    if big.status_code != 200:
        print(f"  big request failed: {big.text[:240]}")

    after_second = await tiny(keys[1])
    after = _header(after_second, "x-ratelimit-remaining-tokens")
    print(f"key#2 after key#1 big: status={after_second.status_code} remaining_tokens={after}")

    try:
        drop = int(before_second) - int(after)
    except ValueError:
        drop = 0
    print("\nVerdict:")
    if drop > 2000:
        print(
            f"  SHARED token bucket: key#2 dropped {drop} tokens after usage on key#1."
        )
        print("  A TPM 429 must skip the whole Groq tier, not just one key.")
        print("  Effective cap: 8K TPM / 200K TPD shared, not 40K/1M.")
    else:
        print(
            f"  Per-key token buckets: key#2 changed by {drop} tokens while key#1 "
            "burned ~5K."
        )
        print("  A TPM 429 on one key leaves the siblings usable.")
    print("  The shared bucket refills over ~1 minute; avoid a demo right after.")
    return 0


async def run(args: argparse.Namespace) -> int:
    keys = _load_keys()
    if not keys:
        print("No GROQ_API_KEY / GROQ_API_KEYS found in the root .env", file=sys.stderr)
        return 2
    print(f"Groq quota probe: {len(keys)} key(s), model={args.model}, requests={args.requests}")
    print("Keys are never printed; key#N is stable for this run.\n")

    results: list[dict[str, str | int]] = []
    async with httpx.AsyncClient(timeout=60.0) as client:
        if args.tpm_probe:
            return await _run_tpm_probe(client, keys, args)
        for i in range(args.requests):
            index = i % len(keys)
            result = await _one_request(
                client,
                base_url=args.base_url,
                model=args.model,
                key=keys[index],
            )
            result["key"] = index
            results.append(result)
            status = result["status"]
            flag = "429" if status == 429 else "ok" if status == 200 else "ERR"
            remaining = result.get("x-ratelimit-remaining-requests", "-")
            print(
                f"{i + 1:03d}/{args.requests} {_mask(index):6s} "
                f"status={status:<3} {flag:<3} remaining_requests={remaining}"
            )
            if status == 429:
                # Keep going: the 429 distribution is the evidence.
                await asyncio.sleep(0.2)
            else:
                await asyncio.sleep(args.delay)

    print("\nPer-key summary:")
    for index in range(len(keys)):
        rows = [r for r in results if r["key"] == index]
        statuses = [int(r["status"]) for r in rows]
        ok = statuses.count(200)
        limited = statuses.count(429)
        errors = [s for s in statuses if s not in (200, 429)]
        last = rows[-1] if rows else {}
        print(
            f"  {_mask(index)}: requests={len(rows)} ok={ok} 429={limited} "
            f"other_errors={errors or '-'} "
            f"remaining_requests={last.get('x-ratelimit-remaining-requests', '-')} "
            f"limit_requests={last.get('x-ratelimit-limit-requests', '-')}"
        )

    print("\nRate-limit headers observed (last response per key):")
    for index in range(len(keys)):
        rows = [r for r in results if r["key"] == index]
        if not rows:
            continue
        last = rows[-1]
        values = " ".join(f"{h}={last.get(h, '-')}" for h in _RATE_HEADERS)
        print(f"  {_mask(index)}: {values}")

    print("\nInterpretation:")
    print("  - Remaining REQUEST counters can differ per key: each key has its own")
    print("    1,000 RPD, so the pool has 5,000 requests/day.")
    print("  - The TOKEN bucket was measured SHARED (run --tpm-probe to re-check):")
    print("    effective 8K TPM / 200K TPD for the whole pool.")
    print("  - 429s at ~30 requests/minute/key are RPM limits, not the daily cap.")
    print("  - The binding limit is the shared 200K TPD token bucket, not requests.")
    print("  - At ~7K counted tokens/call that is ~28 calls/day; at ~1.4K it is")
    print("    ~140. Cached prompt tokens do not count, so measure real usage.")
    limited = sum(1 for r in results if int(r["status"]) == 429)
    if limited:
        print(f"  - {limited}/{len(results)} requests hit 429; do not run a demo immediately after.")
    else:
        print("  - No 429s in this burst.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requests", type=int, default=40)
    parser.add_argument(
        "--tpm-probe",
        action="store_true",
        help="Run only the shared-token-bucket probe (~5K tokens).",
    )
    parser.add_argument("--model", default=os.getenv("GROQ_MODEL", DEFAULT_MODEL))
    parser.add_argument("--base-url", default=os.getenv("GROQ_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument(
        "--delay",
        type=float,
        default=0.0,
        help="Seconds between successful requests (default 0; keep the burst under ~60s).",
    )
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
