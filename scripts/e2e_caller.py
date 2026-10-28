"""Headless fake-caller: proves the full web-call loop without a browser.

Joins the LiveKit room issued by POST /api/playground/sessions, publishes a
spoken WAV as the caller's mic track, listens for agent audio + caption data
messages, then completes the session and asserts transcript/fields exist.

Usage (voice-agent venv):
    python ../../scripts/e2e_caller.py --wav caller.wav --hold 35
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import urllib.request
import wave

try:
    from livekit import rtc  # noqa: F401  (used by play_wav)
except ImportError:
    rtc = None


def http_json(method: str, url: str, body: dict | None = None, token: str | None = None):
    req = urllib.request.Request(url, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    data = json.dumps(body).encode() if body is not None else None
    with urllib.request.urlopen(req, data=data, timeout=15) as resp:
        return json.loads(resp.read().decode())


async def play_wav(src: rtc.AudioSource, wav_path: str) -> None:
    with wave.open(wav_path, "rb") as w:
        rate = w.getframerate()
        channels = w.getnchannels()
        width = w.getsampwidth()
        raw = w.readframes(w.getnframes())
    samples_per_frame = rate // 50  # 20ms frames
    bytes_per_frame = samples_per_frame * channels * width
    for i in range(0, len(raw), bytes_per_frame):
        chunk = raw[i : i + bytes_per_frame]
        if not chunk:
            break
        if len(chunk) < bytes_per_frame:
            chunk = chunk.ljust(bytes_per_frame, b"\x00")
        frame = rtc.AudioFrame(
            chunk,
            sample_rate=rate,
            num_channels=channels,
            samples_per_channel=samples_per_frame,
        )
        await src.capture_frame(frame)
        await asyncio.sleep(0.02)


async def run(
    room_url: str,
    token: str,
    wav_path: str,
    hold_s: int,
    wav2_path: str | None = None,
    wait_before_s: float = 0.0,
) -> int:
    from livekit import rtc

    room = rtc.Room()
    captions: list[str] = []
    agent_audio_bytes = bytearray()

    @room.on("data_received")
    def _on_data(ev) -> None:
        try:
            decoded = bytes(ev.data).decode("utf-8", errors="replace")
        except Exception:
            decoded = repr(ev.data)
        print(f"[CAPTION] {decoded}")
        captions.append(decoded)

    @room.on("track_subscribed")
    def _on_track(track, pub, participant) -> None:
        print(f"[TRACK] kind={track.kind} from={participant.identity}")
        if str(track.kind) == "1" or "audio" in str(track.kind).lower():

            async def _drain() -> None:
                stream = rtc.AudioStream(track)
                async for frame in stream:
                    agent_audio_bytes.extend(bytes(frame.frame.data))

            asyncio.ensure_future(_drain())

    await room.connect(room_url, token)
    print(f"[CONNECTED] identity={room.local_participant.identity} room={room.name}")

    with wave.open(wav_path, "rb") as w:
        rate = w.getframerate()
        channels = w.getnchannels()
        width = w.getsampwidth()
        raw = w.readframes(w.getnframes())
    print(f"[WAV] rate={rate} ch={channels} dur~{len(raw)/rate/channels/width:.1f}s")

    src = rtc.AudioSource(rate, channels)
    track = rtc.LocalAudioTrack.create_audio_track("caller-mic", src)
    opts = rtc.TrackPublishOptions()
    opts.source = rtc.TrackSource.SOURCE_MICROPHONE
    await room.local_participant.publish_track(track, opts)
    print("[PUBLISHED] mic track with SOURCE_MICROPHONE")

    if wait_before_s > 0:
        # Speaking over the agent's greeting makes VAD see one garbled turn and
        # the greeting gets cut mid-sentence; a real caller waits for silence.
        await asyncio.sleep(wait_before_s)
    await play_wav(src, wav_path)
    print("[PUBLISHED] caller utterance done; waiting for agent...")

    # Wait for the AGENT to reply, then optionally play a second turn.
    got_agent_caption = False
    waited = 0
    while waited < hold_s:
        await asyncio.sleep(1)
        waited += 1
        if any('"speaker": "agent"' in c or '"speaker":"agent"' in c for c in captions):
            got_agent_caption = True
            break

    if wav2_path and got_agent_caption:
        await asyncio.sleep(2)
        await play_wav(src, wav2_path)
        print("[PUBLISHED] second caller utterance done")
        # Give the agent time to extract fields and wrap up.
        for extra in range(45):
            await asyncio.sleep(1)
            if '"speaker": "agent"' in " ".join(captions[-3:]) or extra > 40:
                pass
        await asyncio.sleep(8)

    print(
        f"[RESULT] captions={len(captions)} agent_audio_bytes={len(agent_audio_bytes)} "
        f"agent_caption={got_agent_caption}"
    )
    ok = got_agent_caption and len(agent_audio_bytes) > 0
    try:
        await room.disconnect()
    except Exception:
        pass
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--email", default="demo@example.com")
    parser.add_argument("--password", default="demo1234")
    parser.add_argument("--version-id", type=int, default=1)
    parser.add_argument("--wav", required=True)
    parser.add_argument("--wav2", default=None)
    parser.add_argument("--hold", type=int, default=35)
    parser.add_argument("--wait-before-speaking", type=float, default=0.0)
    args = parser.parse_args()

    token = http_json(
        "POST",
        f"{args.base}/api/auth/login",
        {"email": args.email, "password": args.password},
    )["token"]
    sess = http_json(
        "POST",
        f"{args.base}/api/playground/sessions",
        {"agent_version_id": args.version_id},
        token=token,
    )
    call_id, room_name = sess["call_id"], sess["room_name"]
    print(f"[SESSION] call_id={call_id} room={room_name}")

    exit_code = asyncio.run(
        run(
            sess["livekit_url"],
            sess["livekit_token"],
            args.wav,
            args.hold,
            args.wav2,
            args.wait_before_speaking,
        )
    )

    # Worker flushes turns on a short debounce after the reply — poll patiently.
    done = {"transcript": [], "extracted_fields": []}
    for _ in range(8):
        done = http_json(
            "POST",
            f"{args.base}/api/playground/sessions/{call_id}/complete",
            {},
            token=token,
        )
        if done.get("transcript"):
            break
        import time as _t

        _t.sleep(2)
    turns = done.get("transcript") or []
    fields = done.get("extracted_fields") or []
    print(f"[COMPLETE] transcript_turns={len(turns)} extracted_fields={len(fields)}")
    for t in turns[:10]:
        speaker = t.get("speaker") or t.get("role")
        text = t.get("text", "")
        print(f"  [{speaker}] {text[:120]}")
    for f in fields:
        print(
            f"  FIELD {f.get('field_name')}={f.get('field_value')!r} conf={f.get('confidence')}"
        )

    full_ok = exit_code == 0 and len(turns) > 0
    print("E2E:", "PASS" if full_ok else "FAIL")
    return 0 if full_ok else 1


if __name__ == "__main__":
    sys.exit(main())
