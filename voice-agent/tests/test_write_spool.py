import json

import httpx

from app.backend_client import BackendClient
from app.write_spool import WriteSpool


def test_enqueue_and_flush(tmp_path):
    sent = []

    def sender(path, payload):
        sent.append((path, payload))
        return True

    spool = WriteSpool(tmp_path / "spool.jsonl", sender=sender)
    spool.enqueue("/internal/calls/c1/complete", {"status": "completed"})
    assert spool.spool_path.exists()
    assert spool.flush_once() == 1
    assert sent == [("/internal/calls/c1/complete", {"status": "completed"})]
    assert not spool.spool_path.exists()


def test_flush_retries_only_failures(tmp_path):
    attempts = []

    def sender(path, payload):
        attempts.append(payload)
        return len(attempts) >= 2

    spool = WriteSpool(tmp_path / "spool.jsonl", sender=sender)
    spool.enqueue("/p", {"n": 1})
    spool.enqueue("/p", {"n": 2})
    assert spool.flush_once() == 1
    assert spool.spool_path.read_text(encoding="utf-8").count("\n") == 1


class _FailingClient:
    async def post(self, *args, **kwargs):
        raise httpx.ConnectError("backend down")


def test_failed_post_is_spooled(tmp_path, monkeypatch):
    import asyncio

    monkeypatch.setenv("AGENT_SPOOL_DIR", str(tmp_path))
    client = BackendClient("http://backend", "token", client=_FailingClient())
    ok = asyncio.run(client.post_complete("c1", status="completed"))
    assert ok is False
    spool_file = tmp_path / "writes.jsonl"
    assert spool_file.exists()
    record = json.loads(spool_file.read_text(encoding="utf-8").splitlines()[-1])
    assert record["payload"]["status"] == "completed"
