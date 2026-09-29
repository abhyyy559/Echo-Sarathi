"""Create the EchoSarathi Indian-names pronunciation dictionary (v1).

Reads CARTESIA_API_KEY from the repo .env (never printed). Prints only the
new dictionary ID + item count. Safe to re-run: creates a NEW dictionary
each time (old ones are left untouched — delete superseded ones in the
Cartesia dashboard).
"""
import json
import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(ROOT, ".env")


def load_env(path):
    values = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                values[key.strip()] = val.strip()
    return values


ITEMS = [
    ("Aarav", "AA-ruv"),
    ("Abhi", "UB-bhee"),
    ("Suresh", "soo-RESH"),
    ("Pardhu", "PAR-dhoo"),
    ("Priya", "PREE-yaa"),
    ("Riya", "REE-yaa"),
    ("Ananya", "uh-NUN-yaa"),
    ("Rajesh", "raa-JESH"),
    ("Kumar", "koo-MAR"),
    ("Devi", "DHEY-vee"),
    ("Rao", "raa-O"),
    ("Iyer", "EYE-yer"),
    ("Rohan", "RO-hun"),
    ("Meera", "MEE-raa"),
    ("Arjun", "UR-joon"),
    ("Karan", "kuh-RUN"),
    ("Dhanu", "DHAN-oo"),
    ("Srinivas", "sree-nee-VAAS"),
    ("Lakshmi", "LUK-shmee"),
    ("Venkata", "ven-KUH-tuh"),
]

payload = json.dumps({
    "name": "echosarathi-indian-names-v1",
    "description": "Common Indian student/parent names, sounds-like guidance for clear TTS pronunciation. v1 — extend as testing reveals misses.",
    "items": [{"text": t, "pronunciation": p, "case_sensitive": False} for t, p in ITEMS],
}).encode()

key = load_env(ENV_PATH).get("CARTESIA_API_KEY", "")
if not key:
    print("CARTESIA_API_KEY missing from .env", file=sys.stderr)
    sys.exit(1)

req = urllib.request.Request(
    "https://api.cartesia.ai/pronunciation-dicts/",
    data=payload,
    headers={
        "Authorization": f"Bearer {key}",
        "Cartesia-Version": "2025-04-16",
        "Content-Type": "application/json",
    },
    method="POST",
)
with urllib.request.urlopen(req, timeout=30) as resp:
    body = json.loads(resp.read().decode())
print("dictionary_id:", body.get("id"))
print("items:", len(body.get("items", [])))
