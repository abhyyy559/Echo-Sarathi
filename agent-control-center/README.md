# Agent Control Center

Local-first control plane for your coding agents. It inventories Codex, Claude Code, and OpenCode; builds a skills catalog; and manages an OpenRouter policy that blocks paid models by default.

## Quick start

```powershell
cd "agent-control-center"
node agent-control-center.mjs inventory
node agent-control-center.mjs dashboard
```

Open `out/dashboard.html` in a browser.

## OpenRouter refresh

Do **not** place keys in this project. Store your OpenRouter key in the current Windows user environment and open a new terminal:

```powershell
[Environment]::SetEnvironmentVariable('OPENROUTER_API_KEY', 'your-key', 'User')
```

Then refresh the live catalog and rebuild the dashboard:

```powershell
node agent-control-center.mjs refresh-openrouter
node agent-control-center.mjs dashboard
```

The refresh uses the documented `GET /api/v1/models` endpoint. It saves only model metadata, never the key.

## Commands

| Command | Purpose |
| --- | --- |
| `inventory` | Scan installed coding agents and skill manifests. |
| `refresh-openrouter` | Fetch current OpenRouter models and create an ordered, free-only list. |
| `dashboard` | Generate `out/dashboard.html` from the most recent inventory. |
| `export-adapters` | Produce per-agent guidance files in `out/adapters/`. |
| `all` | Run inventory, optional OpenRouter refresh, dashboard, and adapters. |

## Policy

`config/routing-policy.json` is the source of truth. The initial policy is **free-only**, with paid models excluded. Change it only when you consciously want paid routing. No billing account, provider account, or remote configuration is deleted by this tool.

## Applying shared workflow

Use the files exported by `export-adapters` as global guidance for each agent. They intentionally share the same operating principles while preserving each tool's native configuration model. Review generated instructions before putting them in a global agent directory.
