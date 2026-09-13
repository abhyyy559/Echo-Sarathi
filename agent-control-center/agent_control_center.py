#!/usr/bin/env python3
"""Local inventory, routing-policy, and dashboard utility for coding agents."""
from __future__ import annotations

import argparse
import html
import json
import os
import shutil
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "out"
POLICY_FILE = ROOT / "config" / "routing-policy.json"
INVENTORY_FILE = OUT / "inventory.json"
MODELS_FILE = OUT / "openrouter-models.json"


def now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def read_json(path: Path, default: Any) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def skill_name(path: Path) -> str:
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines()[:30]:
            if line.startswith("name:"):
                return line.split(":", 1)[1].strip().strip('"')
    except OSError:
        pass
    return path.parent.name


def find_skills(base: Path, source: str) -> list[dict[str, str]]:
    if not base.exists():
        return []
    result: list[dict[str, str]] = []
    for path in base.rglob("SKILL.md"):
        result.append({"name": skill_name(path), "source": source, "path": str(path)})
    return result


def inventory() -> dict[str, Any]:
    home = Path.home()
    agents = []
    for executable, label in [("codex", "Codex"), ("claude", "Claude Code"), ("opencode", "OpenCode")]:
        location = shutil.which(executable)
        agents.append({"name": label, "command": executable, "installed": bool(location), "path": location})

    skills = []
    skills += find_skills(home / ".codex" / "skills", "Codex system/global")
    skills += find_skills(home / ".codex" / "plugins" / "cache", "Codex plugin cache")
    skills += find_skills(home / ".claude" / "plugins", "Claude plugin cache")
    unique = {(item["name"], item["path"]): item for item in skills}
    return {"generatedAt": now(), "agents": agents, "skills": sorted(unique.values(), key=lambda x: (x["name"].lower(), x["source"]))}


def is_free(model: dict[str, Any]) -> bool:
    pricing = model.get("pricing") or {}
    values = [pricing.get(key) for key in ("prompt", "completion", "request", "image", "web_search")]
    numeric = [str(value) for value in values if value is not None]
    return bool(numeric) and all(value in {"0", "0.0", "0.00"} for value in numeric)


def supports(model: dict[str, Any], parameter: str) -> bool:
    return parameter in (model.get("supported_parameters") or [])


def rank_free_models(models: list[dict[str, Any]], policy: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = [model for model in models if is_free(model)]
    if policy.get("requireToolCalling"):
        with_tools = [model for model in candidates if supports(model, "tools")]
        candidates = with_tools or candidates
    def sort_key(model: dict[str, Any]) -> tuple[Any, ...]:
        architecture = model.get("architecture") or {}
        return (
            0 if supports(model, "tools") else 1,
            -int(model.get("context_length") or 0),
            -(model.get("top_provider") or {}).get("max_completion_tokens", 0),
            str(model.get("name") or model.get("id") or "").lower(),
        )
    return sorted(candidates, key=sort_key)


def refresh_openrouter() -> dict[str, Any]:
    key = os.environ.get("OPENROUTER_API_KEY")
    request = urllib.request.Request("https://openrouter.ai/api/v1/models", headers={"Accept": "application/json"})
    if key:
        request.add_header("Authorization", f"Bearer {key}")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except urllib.error.URLError as exc:
        raise SystemExit(f"OpenRouter catalog refresh failed: {exc.reason}") from exc
    policy = read_json(POLICY_FILE, {})
    models = payload.get("data", [])
    ranked = rank_free_models(models, policy)
    output = {
        "generatedAt": now(),
        "authenticated": bool(key),
        "source": "https://openrouter.ai/api/v1/models",
        "policy": policy,
        "totalModels": len(models),
        "freeEligibleModels": len(ranked),
        "fallback": policy.get("fallback"),
        "models": ranked,
    }
    write_json(MODELS_FILE, output)
    return output


def cell(value: Any) -> str:
    return html.escape(str(value if value is not None else "—"))


def dashboard() -> Path:
    inv = read_json(INVENTORY_FILE, inventory())
    models = read_json(MODELS_FILE, {"models": [], "generatedAt": None, "fallback": "openrouter/free"})
    policy = read_json(POLICY_FILE, {})
    skills_rows = "".join(f"<tr><td>{cell(s['name'])}</td><td>{cell(s['source'])}</td></tr>" for s in inv["skills"])
    agents_rows = "".join(f"<tr><td>{cell(a['name'])}</td><td>{'Installed' if a['installed'] else 'Not found'}</td><td>{cell(a['path'])}</td></tr>" for a in inv["agents"])
    model_rows = "".join(
        f"<tr><td>{cell(m.get('name'))}</td><td>{cell(m.get('id'))}</td><td>{cell(m.get('context_length'))}</td><td>{'Yes' if supports(m, 'tools') else 'No'}</td></tr>"
        for m in models["models"][:100]
    ) or "<tr><td colspan='4'>No live catalog yet. Run refresh-openrouter.</td></tr>"
    page = f"""<!doctype html><html><head><meta charset='utf-8'><title>Agent Control Center</title><style>
body{{font-family:system-ui;max-width:1200px;margin:2rem auto;background:#10141c;color:#e9edf5;padding:0 1rem}} h1,h2{{color:#8dd6ff}} .card{{background:#19212e;padding:1rem 1.25rem;margin:1rem 0;border-radius:10px}} table{{border-collapse:collapse;width:100%}} td,th{{padding:.55rem;border-bottom:1px solid #344154;text-align:left}} code{{color:#a7f3d0}}</style></head><body>
<h1>Agent Control Center</h1><p>Generated {cell(now())}. Local-only dashboard; secrets are never displayed.</p>
<div class='card'><h2>Routing policy</h2><p>Mode: <code>{cell(policy.get('mode'))}</code> · Paid models: <code>{'allowed' if policy.get('allowPaidModels') else 'blocked'}</code> · Fallback: <code>{cell(models.get('fallback'))}</code></p><p>OpenRouter snapshot: {cell(models.get('generatedAt') or 'not refreshed')} · Free eligible models: {cell(models.get('freeEligibleModels', 0))}</p></div>
<div class='card'><h2>Coding agents</h2><table><tr><th>Agent</th><th>Status</th><th>Command</th></tr>{agents_rows}</table></div>
<div class='card'><h2>Skills ({len(inv['skills'])})</h2><table><tr><th>Name</th><th>Source</th></tr>{skills_rows}</table></div>
<div class='card'><h2>OpenRouter free-model ranking</h2><table><tr><th>Model</th><th>ID</th><th>Context</th><th>Tools</th></tr>{model_rows}</table></div>
</body></html>"""
    path = OUT / "dashboard.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(page, encoding="utf-8")
    return path


def export_adapters() -> list[Path]:
    destination = OUT / "adapters"
    files = []
    for source in (ROOT / "adapters").rglob("*.md"):
        target = destination / source.relative_to(ROOT / "adapters")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        files.append(target)
    workflow = destination / "AGENT_WORKFLOW.md"
    workflow.write_text((ROOT / "shared" / "AGENT_WORKFLOW.md").read_text(encoding="utf-8"), encoding="utf-8")
    return files + [workflow]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["inventory", "refresh-openrouter", "dashboard", "export-adapters", "all"])
    args = parser.parse_args()
    if args.command in {"inventory", "all"}:
        data = inventory(); write_json(INVENTORY_FILE, data); print(f"Inventory: {len(data['agents'])} agents, {len(data['skills'])} skills")
    if args.command in {"refresh-openrouter", "all"}:
        if os.environ.get("OPENROUTER_API_KEY"):
            data = refresh_openrouter(); print(f"OpenRouter: {data['freeEligibleModels']} free eligible models")
        else:
            print("OpenRouter skipped: OPENROUTER_API_KEY is not set.")
    if args.command in {"dashboard", "all"}:
        print(f"Dashboard: {dashboard()}")
    if args.command in {"export-adapters", "all"}:
        print(f"Adapters exported: {len(export_adapters())}")


if __name__ == "__main__":
    main()
