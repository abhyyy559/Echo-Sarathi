"""Seed review-demo content: campaign + roster import + one playground text turn.

Usage (from backend/): ..\\.venv\\Scripts\\python.exe ..\\scripts\\review2_seed.py
Idempotent-ish: creates a NEW campaign each run; reuses the seeded agent v1.
"""
from __future__ import annotations

import json
import sys
import urllib.request

API = "http://localhost:8000"


def _req(method: str, path: str, token: str | None = None, body=None, files=None):
    data: bytes | None = None
    headers: dict[str, str] = {}
    if files is not None:
        boundary = "----review2boundary"
        parts: list[bytes] = []
        for key, value in files["fields"].items():
            parts.append(
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"\r\n\r\n{value}\r\n".encode()
            )
        fname, fbytes, ftype = files["file"]
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{fname}"\r\nContent-Type: {ftype}\r\n\r\n'.encode()
            + fbytes
            + b"\r\n"
        )
        parts.append(f"--{boundary}--\r\n".encode())
        data = b"".join(parts)
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    elif body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(API + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()[:500]


def main() -> None:
    import urllib.error  # noqa: E402  (kept local so import errors surface cleanly)

    status, login = _req(
        "POST",
        "/api/auth/login",
        body={"email": "demo@example.com", "password": "demo1234"},
    )
    assert status == 200, f"login failed: {login}"
    token = login["token"]

    status, agents = _req("GET", "/api/agents", token)
    assert status == 200, agents
    agent = agents[0]
    status, versions = _req("GET", f"/api/agents/{agent['id']}/versions", token)
    version_id = versions[-1]["id"]
    print(f"agent={agent['id']} version={version_id}")

    status, campaign = _req(
        "POST", "/api/campaigns", token, {"name": "Class 10 Absentees - Review Demo"}
    )
    assert status == 201, campaign
    cid = campaign["id"]
    print(f"campaign={cid}")

    with open("../sample_campaign_contacts.csv", "rb") as fh:
        csv_bytes = fh.read()
    mapping = {
        "name_col": "name",
        "phone_col": "phone",
        "id_col": None,
        "consent_col": None,
        "custom": {
            "student_name": "student_name",
            "parent_name": "parent_name",
            "class_section": "class_section",
            "absent_date": "absent_date",
        },
    }
    status, result = _req(
        "POST",
        f"/api/campaigns/{cid}/contacts/import",
        token,
        files={
            "fields": {"mapping": json.dumps(mapping), "consent_default": "true"},
            "file": ("roster.csv", csv_bytes, "text/csv"),
        },
    )
    assert status == 200, result
    print(f"imported={result}")

    status, session = _req(
        "POST", "/api/playground/sessions", token, {"agent_version_id": version_id}
    )
    assert status == 200, session
    call_id = session["call_id"]
    print(f"playground call={call_id}")
    status, turn = _req(
        "POST",
        f"/api/playground/sessions/{call_id}/turns",
        token,
        {"text": "Good morning. My son Aarav has had fever since yesterday."},
    )
    print(f"turn status={status} reply={(turn.get('reply_text') or '')[:120]}")
    print("DONE")


if __name__ == "__main__":
    sys.exit(main())
