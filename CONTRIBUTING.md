# Contributing

This repository runs a production voice-calling platform. Every merge to
`master` deploys to Render (API) and Vercel (site) within a couple of minutes,
so `master` is protected and changes land through pull requests.

## Workflow

1. Branch off `master`:

   ```bash
   git checkout -b feat/short-name
   ```

2. Commit in the repository's conventional style, scoped to the area touched:
   `fix(dialer): ...`, `feat(campaign): ...`, `test(e2e): ...`, `docs: ...`.
3. Push the branch and open a pull request against `master`.
4. One approval is required to merge. `master` blocks force-pushes and
   deletions; there is no CI gate yet, so a reviewer has to run the tests below.

Outside contributors cannot push branches to this repository. Fork it, push to
your fork, and open the pull request from there.

## Before opening a pull request

```bash
cd backend && python -m pytest -q          # API and services
cd voice-agent && python -m pytest -q      # call pipeline
cd frontend && npm test && npm run build   # UI units and production build
```

Run the suites for the areas you touched; the full backend suite is the one that
matters for dialing, billing and consent changes.

## Never commit

- `.env`, `.deploy.env`, or any file containing a real key, token, password,
  phone number or customer record.
- A new provider key. Add the variable **name** to `.env.example` with an empty
  or placeholder value, and send the real value to the maintainer out of band.

Secret scanning and push protection are enabled on this repository: a commit
containing a credential is rejected before it is pushed.

## Calls, consent and phone numbers

- Do not place outbound calls to real phone numbers from a development machine.
  Test calls go only to the numbers listed in `TEST_PHONE_NUMBERS`.
- `CONSENT_ENFORCEMENT` and the outbound allowlist are production guardrails.
  A pull request that disables or weakens them will not be merged.
- KYC, DLT registration and carrier terms apply to every number this platform
  dials from. Never add a number you are not authorised to call.

## Things that are generated

`frontend/src/od-*.css` files are generated and say "do not hand-edit" at the
top. Make visual changes in `styles.css`, `saas.css` or `theme-light.css`
instead, or regenerate the page CSS.
