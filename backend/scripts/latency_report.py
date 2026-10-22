"""Read-only: recent calls + per-turn latency breakdown from the production DB."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))

import psycopg2  # noqa: E402

DSN = os.environ["DATABASE_URL"]
if DSN.startswith("postgres://"):
    DSN = "postgresql://" + DSN[len("postgres://") :]

SQL_CALLS = """
select id, status, created_at, started_at, answered_at, ended_at, duration_seconds,
       contact_id, agent_version_id
from calls order by id desc limit 6
"""
SQL_TURNS = """
select turn_index, speaker, left(text, 70) as text,
       stt_final_ms, llm_first_token_ms, tts_first_audio_ms, e2e_ms
from transcripts where call_id = %s order by turn_index
"""

with psycopg2.connect(DSN) as conn, conn.cursor() as cur:
    cur.execute(SQL_CALLS)
    calls = cur.fetchall()
    for row in calls:
        cid = row[0]
        print(
            f"call {cid}: status={row[1]} created={row[2]} answered={row[4]} "
            f"ended={row[5]} dur={row[6]}s"
        )
        cur.execute(SQL_TURNS, (cid,))
        for t in cur.fetchall():
            print(
                f"   t{t[0]:<2} {t[1]:<8} stt={t[3]} llm={t[4]} tts={t[5]} e2e={t[6]} | {t[2]!r}"
            )
        # aggregates
        cur.execute(
            """select count(*), avg(stt_final_ms), avg(llm_first_token_ms),
                      avg(tts_first_audio_ms), avg(e2e_ms),
                      max(e2e_ms)
               from transcripts where call_id = %s and speaker = 'agent'""",
            (cid,),
        )
        a = cur.fetchone()
        print(
            f"   agent turns={a[0]} avg stt={a[1]} llm={a[2]} tts={a[3]} "
            f"e2e={a[4]} max_e2e={a[5]}"
        )
        print()