"""Sync /domain-configs/*.json files into the domain_configs table.

Accepted file shape (all keys optional except the config body itself)::

    {
      "name": "absent-student",        # slug; defaults to filename stem
      "display_name": "Absent Student",
      "version": 3,                    # informational only; DB version is managed here
      ...rest of the object...         # OR nested under a "config" key
    }

If a ``config`` key exists its value is stored as the config JSON; otherwise
the whole object minus ``name``/``display_name``/``version`` is stored.
Re-syncing unchanged files is a no-op; changed files bump ``version``.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DomainConfig

logger = logging.getLogger(__name__)

_META_KEYS = {"name", "display_name", "version"}


def _parse_config_file(path: Path) -> tuple[str, str, dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError(f"{path.name}: top-level JSON must be an object")
    name = str(data.get("name") or path.stem).strip()
    display_name = str(data.get("display_name") or name.replace("-", " ").replace("_", " ").title())
    if "config" in data and isinstance(data["config"], dict):
        config = data["config"]
    else:
        config = {k: v for k, v in data.items() if k not in _META_KEYS}
    return name, display_name, config


def sync_domain_configs(db: Session, configs_dir: str | Path) -> list[str]:
    """Upsert every *.json in the directory. Returns synced config names.

    A missing directory is not an error (logs a warning, returns []).
    Manual orphan cleanup (no API): DELETE FROM domain_configs WHERE name IN
    ('hospital-appointment','schema'); Agents: DELETE /api/agents/{id} archives
    (needs bearer).
    """
    directory = Path(configs_dir)
    if not directory.is_absolute():
        from app.database import repo_relative

        directory = repo_relative(str(directory))
    if not directory.is_dir():
        logger.warning("domain configs dir not found: %s", directory)
        return []

    synced: list[str] = []
    for path in sorted(p for p in directory.glob("*.json") if p.name != "schema.json"):
        try:
            name, display_name, config = _parse_config_file(path)
        except (ValueError, json.JSONDecodeError) as exc:
            logger.warning("skipping invalid domain config %s: %s", path.name, exc)
            continue
        existing = db.scalar(select(DomainConfig).where(DomainConfig.name == name))
        if existing is None:
            db.add(
                DomainConfig(
                    name=name, display_name=display_name, config=config, version=1
                )
            )
            synced.append(name)
        elif existing.config != config or existing.display_name != display_name:
            existing.config = config
            existing.display_name = display_name
            existing.version = (existing.version or 1) + 1
            synced.append(name)
    db.commit()
    if synced:
        logger.info("domain configs synced: %s", ", ".join(synced))
    return synced
