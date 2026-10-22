"""End-to-end worker check: join a playground room and watch for the agent.

Signs in to the deployed API, creates a playground session, joins the room as a
real WebRTC participant (which is what triggers LiveKit's automatic agent
dispatch), and waits for the configured worker to appear and publish audio.

    python .deploy/e2e_worker_check.py

Exit 0 = the agent joined a production room. Exit 1 = it did not.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import urllib.error
import urllib.request


API = os.environ.get("API_BASE", "https://echosarathi-api.onrender.com").rstrip("/")
EMAIL = os.environ["DEMO_EMAIL"]
PASSWORD = os.environ["DEMO_PASSWORD"]
TIMEOUT = int(os.environ.get("AGENT_TIMEOUT", "60"))


def call(path: str, payload: dict, token: str | None = None) -> dict:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(
        f"{API}{path}", data=json.dumps(payload).encode(), headers=headers, method="POST"
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.load(resp)


async def main() -> int:
    from livekit import rtc

    login = call("/api/auth/login", {"email": EMAIL, "password": PASSWORD})
    session = call(
        "/api/playground/sessions",
        {"agent_version_id": 1},
        token=login["token"],
    )
    call_id, room_name = session["call_id"], session["room_name"]
    print(f"session call={call_id} room={room_name} url={session['livekit_url']}")

    room = rtc.Room()
    joined: list[str] = []

    @room.on("participant_connected")
    def _on_join(p: rtc.RemoteParticipant) -> None:
        tracks = [t.name or t.kind for t in p.track_publications.values()] if p.track_publications else []
        joined.append(p.identity)
        print(f"  + {p.identity}  tracks={tracks}")

    @room.on("track_subscribed")
    def _on_track(track: rtc.Track, pub: rtc.RemoteTrackPublication, p: rtc.RemoteParticipant) -> None:
        print(f"  track from {p.identity}: {pub.name or pub.kind} ({pub.kind})")

    try:
        await room.connect(session["livekit_url"], session["livekit_token"])
        print(f"  connected as {room.local_participant.identity}")

        waited = 0.0
        while waited < TIMEOUT:
            agents = [i for i in joined if i.startswith("agent")]
            if agents:
                await asyncio.sleep(3)  # let the published tracks arrive
                print(f"AGENT JOINED: {agents}")
                return 0
            await asyncio.sleep(1)
            waited += 1

        print(f"NO AGENT after {TIMEOUT}s (participants: {joined or 'none'})")
        return 1
    finally:
        await room.disconnect()
        try:
            call(f"/api/playground/sessions/{call_id}/complete", {"outcome": "abandoned"}, token=login["token"])
        except urllib.error.HTTPError as exc:  # cleanup is best-effort
            print(f"  cleanup skipped: HTTP {exc.code}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
