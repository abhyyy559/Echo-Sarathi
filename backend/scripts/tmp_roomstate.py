import asyncio
import sys

sys.path.insert(0, ".")

from dotenv import dotenv_values
from livekit import api


async def main(room_sub: str) -> None:
    cfg = dotenv_values("../.env")
    key = (cfg.get("LIVEKIT_API_KEY") or "").strip()
    secret = (cfg.get("LIVEKIT_API_SECRET") or "").strip()
    lk = api.LiveKitAPI("http://localhost:7880", key, secret)
    rooms = await lk.room.list_rooms(api.ListRoomsRequest())
    for r in rooms.rooms:
        if room_sub not in r.name:
            continue
        print(f"room {r.name} participants={r.num_participants}")
        parts = await lk.room.list_participants(api.ListParticipantsRequest(room=r.name))
        for p in parts.participants:
            tracks = [
                (str(t.source), (t.sid or "")[:10], "muted" if t.muted else "live")
                for t in p.tracks
            ]
            print(f"  {p.identity} state={p.state} tracks={tracks}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "playground"))
