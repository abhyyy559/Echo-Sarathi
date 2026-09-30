"""Loopback: publisher plays speech, observer measures received energy.

Proves (or disproves) that published audio actually flows through the LiveKit
server as audible speech. If the observer hears energy, the publish path is
fine and any STT failure is on the consumer side.
"""
from __future__ import annotations

import argparse
import asyncio
import struct
import sys
import time

import httpx
from livekit import rtc


async def main_async(url: str, token_a: str, token_b: str, wav_path: str) -> int:
    with open(wav_path, "rb") as f:
        raw = f.read()
    marker = raw.find(b"data")
    pcm = raw[marker + 8 :] if marker > 0 else raw

    pub_room = rtc.Room()
    sub_room = rtc.Room()
    received_samples: list[int] = []
    got_track = asyncio.Event()

    @sub_room.on("track_subscribed")
    def _on_track(track: rtc.Track, *_a: object) -> None:
        if track.kind != rtc.TrackKind.KIND_AUDIO:
            return
        got_track.set()
        stream = rtc.AudioStream(track)

        async def _drain() -> None:
            async for event in stream:
                frame = getattr(event, "frame", event)
                data = bytes(frame.data)
                n = len(data) // 2
                received_samples.extend(struct.unpack("<" + "h" * n, data[: n * 2]))

        asyncio.ensure_future(_drain())

    await pub_room.connect(url, token_a)
    await sub_room.connect(url, token_b)

    source = rtc.AudioSource(48000, 1)
    track = rtc.LocalAudioTrack.create_audio_track("loop-mic", source)
    await pub_room.local_participant.publish_track(track)
    # Speak 2s of the WAV (assume 48kHz mono PCM16; resample in test if needed).
    step = 960 * 2
    for off in range(0, min(len(pcm), 48000 * 2 * 2), step):
        chunk = pcm[off : off + step]
        if len(chunk) < step:
            chunk += b"\x00" * (step - len(chunk))
        await source.capture_frame(rtc.AudioFrame(chunk, 48000, 1, 960))
        await asyncio.sleep(0.02)
    await asyncio.sleep(2.0)

    await pub_room.disconnect()
    await sub_room.disconnect()
    n = len(received_samples)
    peak = max((abs(s) for s in received_samples), default=0)
    nonzero = sum(1 for s in received_samples if abs(s) > 200)
    print(f"received_samples={n} peak={peak} nonzero_over_200={nonzero}")
    if n > 20000 and peak > 1000 and nonzero > n * 0.1:
        print("LOOPBACK PASS: speech energy arrived")
        return 0
    print("LOOPBACK FAIL: publisher audio did not arrive as speech")
    return 1


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--url", required=True)
    p.add_argument("--token-a", required=True)
    p.add_argument("--token-b", required=True)
    p.add_argument("--wav", required=True)
    a = p.parse_args()
    sys.exit(asyncio.run(main_async(a.url, a.token_a, a.token_b, a.wav)))


if __name__ == "__main__":
    main()
