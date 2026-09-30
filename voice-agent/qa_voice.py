"""Automated end-to-end voice QA: a scripted caller that phones the agent.

WHY: every voice verification used to need a human with a microphone, and a
human cannot measure latency or repeat the exact same call twice. This joins a
playground room as a fake caller, speaks scripted lines (synthesized with
Deepgram Aura, so no mic needed), and measures the full pipeline:

  caller audio -> STT -> LLM -> TTS -> agent audio + captions

It reports per-turn STT text (proves STT heard), agent replies, latencies,
extraction results, and whether the call ended cleanly. Run it after any
pipeline change instead of asking a human to talk.

Usage (voice-agent venv):
    python qa_voice.py --base-url http://localhost:8000 --email ... --password ...
    python qa_voice.py --version-id 3 --lines "yes" "sick leave" "2nd oct" "no"
"""
from __future__ import annotations

import argparse
import asyncio
import io
import json
import sys
import time
import wave

import httpx
from livekit import rtc


def api(base: str, token: str | None = None) -> httpx.Client:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return httpx.Client(base_url=base, headers=headers, timeout=60.0)


def ensure_login(client: httpx.Client, email: str, password: str) -> str:
    try:
        r = client.post("/api/auth/login", json={"email": email, "password": password})
        r.raise_for_status()
        return r.json()["token"]
    except httpx.HTTPStatusError:
        pass
    name = email.split("@")[0]
    r = client.post(
        "/api/auth/register",
        json={"email": email, "password": password, "name": name, "org_name": name},
    )
    r.raise_for_status()
    return r.json()["token"]


def pick_version(client: httpx.Client) -> int:
    agents = client.get("/api/agents").json()
    if not agents:
        agent = client.post(
            "/api/agents", json={"name": "QA Agent", "description": "automated voice QA"}
        )
        agent.raise_for_status()
        agent_id = agent.json()["id"]
        import pathlib

        config = json.loads(
            pathlib.Path("../domain-configs/absent-student.json").read_text(encoding="utf-8-sig")
        )
        version = client.post(
            f"/api/agents/{agent_id}/versions",
            json={
                "system_prompt": config["system_prompt"],
                "company_context": {"institution": "CMR College of Engineering and Technology"},
                "question_flow": config["question_flow"],
                "extraction_schema": config["extraction_schema"],
                "disclosure_script": config["mandatory_disclosure"],
                "escalation_rules": config["escalation_rules"],
                "voice_settings": {"voice_id": "", "speed": 1.0},
            },
        )
        version.raise_for_status()
        return int(version.json()["id"])
    versions = client.get(f"/api/agents/{agents[0]['id']}/versions").json()
    assert versions, "agent has no versions"
    return int(versions[-1]["id"])


def synthesize(deepgram_key: str, text: str) -> tuple[bytes, int]:
    """Caller utterance as 48kHz mono PCM16 via Deepgram Aura (REST).

    48kHz is requested directly so no resampling is needed (audioop was
    removed in Python 3.13 and numpy is not a dependency). NOTE: Aura returns
    a WAV container even with encoding=linear16, so the 44-byte RIFF header
    must be stripped - publishing it as audio corrupts the first frame and
    shifts every sample.
    """
    with httpx.Client(timeout=60.0) as c:
        r = c.post(
            "https://api.deepgram.com/v1/speak?model=aura-2-thalia-en&encoding=linear16&sample_rate=48000",
            headers={"Authorization": f"Token {deepgram_key}", "Content-Type": "application/json"},
            json={"text": text},
        )
        r.raise_for_status()
        raw = r.content
        if raw[:4] == b"RIFF":
            import struct

            data_at = raw.find(b"data")
            assert data_at > 0, "WAV without data chunk"
            pcm = raw[data_at + 8 :]
        else:
            pcm = raw
        return pcm, 48000


def to_48k_mono(pcm16: bytes, rate: int) -> bytes:
    assert rate == 48000, f"caller audio must be 48kHz, got {rate}"
    return pcm16


class QACaller:
    def __init__(self, url: str, token: str) -> None:
        self.room = rtc.Room()
        self.url = url
        self.token = token
        self.captions: list[dict] = []
        self.agent_audio_frames = 0
        self.agent_seen = asyncio.Event()
        self._reply_event = asyncio.Event()
        self._last_agent_text = ""
        self._mic_source: rtc.AudioSource | None = None
        self._mic_track: rtc.LocalAudioTrack | None = None

    async def connect(self) -> None:
        @self.room.on("data_received")
        def _on_data(packet: rtc.DataPacket) -> None:
            try:
                payload = json.loads(packet.data.decode())
            except Exception:
                return
            if payload.get("type") != "caption":
                return
            self.captions.append(
                {
                    "at": time.time(),
                    "speaker": payload.get("speaker"),
                    "text": payload.get("text"),
                    "final": payload.get("final", True),
                }
            )
            if payload.get("speaker") == "agent" and payload.get("final", True):
                self._last_agent_text = payload.get("text") or ""
                self._reply_event.set()

        @self.room.on("track_subscribed")
        def _on_track(track: rtc.Track, *_a: object) -> None:
            if track.kind == rtc.TrackKind.KIND_AUDIO:
                self.agent_seen.set()
                stream = rtc.AudioStream(track)
                asyncio.ensure_future(self._drain(stream))

        await self.room.connect(self.url, self.token)
        # No default microphone: this caller publishes scripted audio itself.

    async def _drain(self, stream: rtc.AudioStream) -> None:
        try:
            async for _frame in stream:
                self.agent_audio_frames += 1
        except Exception:
            pass

    async def say(self, pcm48: bytes, timeout: float = 30.0) -> dict:
        """Publish one utterance on the persistent mic track, wait for reply."""
        if self._mic_source is None:
            self._mic_source = rtc.AudioSource(48000, 1)
            self._mic_track = rtc.LocalAudioTrack.create_audio_track("qa-mic", self._mic_source)
            await self.room.local_participant.publish_track(self._mic_track)
        self._reply_event.clear()
        start = time.time()
        # 20ms frames paced to real time, then trailing silence so the
        # agent's endpointing fires.
        step = 960 * 2
        for off in range(0, len(pcm48), step):
            chunk = pcm48[off : off + step]
            if len(chunk) < step:
                chunk = chunk + b"\x00" * (step - len(chunk))
            await self._mic_source.capture_frame(rtc.AudioFrame(chunk, 48000, 1, 960))
            await asyncio.sleep(0.02)
        silence = rtc.AudioFrame(b"\x00" * step, 48000, 1, 960)
        for _ in range(40):
            await self._mic_source.capture_frame(silence)
            await asyncio.sleep(0.02)
        spoke_at = time.time()
        try:
            await asyncio.wait_for(self._reply_event.wait(), timeout=timeout)
            replied_at = time.time()
            ok = True
        except asyncio.TimeoutError:
            replied_at = time.time()
            ok = False
        # The mic track stays published for the whole session (like a real
        # caller's microphone) so server-side inspection sees it.
        return {
            "spoke_s": round(spoke_at - start, 2),
            "reply_latency_s": round(replied_at - spoke_at, 2),
            "got_reply": ok,
            "reply_text": self._last_agent_text,
        }

    async def wait_for_agent(self, timeout: float = 45.0) -> bool:
        try:
            await asyncio.wait_for(self.agent_seen.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    async def wait_for_greeting(
        self, timeout: float = 60.0
    ) -> bool:
        """Wait until the agent's opening line is done playing.

        Speaking over the greeting means the input collides with agent audio:
        interruption handling suppresses it, endpointing never fires cleanly,
        and nothing transcribes. A real caller waits for the pause, so the QA
        must too. Estimates speech duration from caption length.
        """
        start = time.time()
        greeting = ""
        while time.time() - start < timeout:
            for caption in self.captions:
                if caption.get("speaker") == "agent" and caption.get("final"):
                    greeting = caption.get("text") or ""
                    break
            if greeting:
                break
            await asyncio.sleep(0.5)
        if not greeting:
            return False
        # ~12 chars/sec + trailing silence so endpointing settles.
        await asyncio.sleep(len(greeting) / 12.0 + 3.0)
        return True


async def main_async(args: argparse.Namespace) -> int:
    client = api(args.base_url)
    token = ensure_login(client, args.email, args.password)
    authed = api(args.base_url, token)
    version_id = args.version_id or pick_version(authed)
    sess = authed.post(
        "/api/playground/sessions",
        json={
            "agent_version_id": version_id,
            "contact": {"student_name": "Abhi", "parent_name": "Ram", "class_section": "10-B"},
        },
    )
    sess.raise_for_status()
    session = sess.json()
    deepgram_key = args.deepgram_key
    if not deepgram_key:
        print("need --deepgram-key (caller voice synthesis)", file=sys.stderr)
        return 2

    caller = QACaller(session["livekit_url"], session["livekit_token"])
    await caller.connect()
    report: dict = {
        "call_id": session["call_id"],
        "room": session["room_name"],
        "version_id": version_id,
        "agent_joined": await caller.wait_for_agent(),
        "turns": [],
    }
    if not report["agent_joined"]:
        report["verdict"] = "FAIL: agent never joined the room"
        print(json.dumps(report, indent=1))
        return 1

    # Let the opening line play fully before speaking (see wait_for_greeting).
    greeted = await caller.wait_for_greeting()
    report["greeting_heard"] = greeted
    if not greeted:
        report["verdict"] = "FAIL: agent never spoke the greeting"
        print(json.dumps(report, indent=1))
        return 1
    for line in args.lines:
        pcm16, rate = await asyncio.to_thread(synthesize, deepgram_key, line)
        turn = await caller.say(to_48k_mono(pcm16, rate))
        turn["said"] = line
        # What did STT hear? Ask the backend transcript for our turns.
        report["turns"].append(turn)
        await asyncio.sleep(2.0)

    if args.hold_open > 0:
        # Stay in the room so the server-side track/subscription state can be
        # inspected from outside while both peers are present.
        print(f"HOLDING room {session['room_name']} open for {args.hold_open}s", flush=True)
        await asyncio.sleep(args.hold_open)

    await caller.room.disconnect()
    # Pull the server-side truth: transcript + fields + completion.
    done = authed.post(f"/api/playground/sessions/{session['call_id']}/complete")
    final = done.json() if done.status_code == 200 else {}
    report["agent_captions"] = [
        c for c in caller.captions if c["speaker"] == "agent" and c["final"]
    ]
    report["user_captions"] = [
        c for c in caller.captions if c["speaker"] == "user" and c["final"]
    ]
    report["agent_audio_frames"] = caller.agent_audio_frames
    report["extracted_fields"] = final.get("extracted_fields", [])
    report["server_transcript"] = [
        {"speaker": t["speaker"], "text": t["text"]}
        for t in final.get("transcript", [])
    ]
    latencies = [t["reply_latency_s"] for t in report["turns"] if t["got_reply"]]
    report["reply_latency_s"] = {
        "n": len(latencies),
        "median": round(sorted(latencies)[len(latencies) // 2], 2) if latencies else None,
        "max": round(max(latencies), 2) if latencies else None,
    }
    missed = sum(1 for t in report["turns"] if not t["got_reply"])
    no_fields = not report["extracted_fields"]
    if not report["agent_joined"]:
        report["verdict"] = "FAIL: agent never joined"
    elif missed:
        report["verdict"] = f"FAIL: agent did not reply to {missed} turn(s)"
    elif no_fields:
        report["verdict"] = "FAIL: no fields extracted"
    elif report["reply_latency_s"]["median"] and report["reply_latency_s"]["median"] > 5:
        report["verdict"] = "WARN: replies too slow for voice"
    else:
        report["verdict"] = "PASS"
    print(json.dumps(report, indent=1))
    return 0 if report["verdict"] == "PASS" else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Automated voice QA caller")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--email", default="qa@example.com")
    parser.add_argument("--password", default="qa123456")
    parser.add_argument("--version-id", type=int, default=0)
    parser.add_argument("--deepgram-key", default="")
    parser.add_argument(
        "--lines",
        nargs="*",
        default=["yes", "sick leave", "2nd october", "no", "bye"],
    )
    parser.add_argument(
        "--hold-open",
        type=int,
        default=0,
        help="After the last line, keep the room open N seconds (for server-side inspection).",
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()
