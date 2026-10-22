"""Probe the Sarvam Bulbul streaming TTS path for a given codec/rate.

Usage: probe_sarvam_codec.py <codec> [rate]
Prints frame counts and total bytes only - never the audio or the key.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".env"))

from livekit.agents import utils  # noqa: E402
from livekit.plugins import sarvam  # noqa: E402

TEXT = "నమస్కారం, ఇది ఒక చిన్న పరీక్ష. మీ విద్యార్థి ఈరోజు గైర్హాజరు గురించి మాట్లాడతాను."


async def main() -> None:
    codec = sys.argv[1] if len(sys.argv) > 1 else "mulaw"
    rate = int(sys.argv[2]) if len(sys.argv) > 2 else 8000
    key = os.getenv("SARVAM_TTS_API") or os.getenv("SARVAM_API_KEY")
    if not key:
        print("no SARVAM key in env")
        return
    tts = sarvam.TTS(
        target_language_code="te-IN",
        model="bulbul:v3",
        speaker="priya",
        speech_sample_rate=rate,
        pace=1.0,
        api_key=key,
        output_audio_codec=codec,
    )
    total = 0
    frames = 0
    first_at = None
    import time

    async with utils.http_context.open():
        tts.prewarm()
        await asyncio.sleep(0.5)
        stream = tts.stream()
        stream.push_text(TEXT)
        stream.end_input()
        start = time.monotonic()
        async for ev in stream:
            if first_at is None:
                first_at = time.monotonic() - start
            frames += 1
            total += len(bytes(ev.frame.data))
            if frames == 1:
                print(
                    f"first frame: rate={ev.frame.sample_rate} ch={ev.frame.num_channels} "
                    f"bytes={len(bytes(ev.frame.data))} ttfb={first_at:.2f}s"
                )
        await stream.aclose()
    print(f"codec={codec} rate={rate} frames={frames} total_bytes={total}")


if __name__ == "__main__":
    asyncio.run(main())