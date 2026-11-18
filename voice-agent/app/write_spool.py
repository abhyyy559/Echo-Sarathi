"""Best-effort JSONL spool for backend writes that must not be lost.

A flaky backend must never crash a voice session, but a transcript or billing
event silently dropped is worse than a delayed one. Failed POSTs are appended
to a local JSONL file and retried on the next turn by ``flush_once()``.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable


class WriteSpool:
    def __init__(
        self,
        path: Path,
        sender: Callable[[str, Any], bool] | None = None,
    ) -> None:
        self.spool_path = Path(path)
        self._sender = sender

    def enqueue(self, path: str, payload: Any) -> None:
        self.spool_path.parent.mkdir(parents=True, exist_ok=True)
        record = {"path": path, "payload": payload}
        with self.spool_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, default=str) + "\n")

    def flush_once(self) -> int:
        """Try every spooled record once. Return how many were delivered."""
        if not self.spool_path.exists() or self._sender is None:
            return 0
        lines = self.spool_path.read_text(encoding="utf-8").splitlines()
        remaining: list[str] = []
        sent = 0
        for line in lines:
            try:
                record = json.loads(line)
                ok = bool(self._sender(record["path"], record["payload"]))
            except Exception:
                ok = False
            if ok:
                sent += 1
            else:
                remaining.append(line)
        if remaining:
            self.spool_path.write_text("\n".join(remaining) + "\n", encoding="utf-8")
        else:
            self.spool_path.unlink(missing_ok=True)
        return sent
