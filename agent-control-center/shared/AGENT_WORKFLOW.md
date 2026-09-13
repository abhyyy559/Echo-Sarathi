# Shared Coding-Agent Workflow

1. Inspect before changing files. Preserve unrelated user changes.
2. Keep credentials in environment variables or an OS-backed secret store; never commit them.
3. Use the configured model policy. The default is free-only OpenRouter routing for compatible tools.
4. Prefer the highest-ranked compatible model, then use the declared fallback chain.
5. Run focused verification after implementation and report the result.
6. Treat paid models, external writes, and credential changes as explicit opt-in actions.

