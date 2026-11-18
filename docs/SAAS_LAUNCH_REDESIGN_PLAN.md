# Echo Sarathi — SaaS launch frontend redesign

Prepared 2026-10-28. Target launch requested: 2026-10-29.
**Status: design approved; frontend implementation in progress.** A target date is not a claim of production readiness.

## 1. Objective and non-negotiable boundary

Deliver a polished, coherent SaaS frontend, led by a new landing page, while preserving the existing working call system. The product remains domain-independent: agents for Indian businesses, with education as one demonstrated use case.

User constraints:
- New branch; existing working version must not be disturbed.
- Inventory all pages before implementation.
- Inspect Outpero and the existing competitor set; use evidence rather than assumptions.
- Apply a consistent, premium startup-grade UI across the product, not just the homepage.
- Parallel agents may own separate frontend lanes.
- Do not change calling, telephony, voice behavior or backend logic during the redesign.

### Isolation already established

- Branch: `redesign/saas-launch`.
- Worktree: `C:/Users/home/OneDrive/Documents/projects/echo-sarathi-saas-redesign`.
- Initial base commit: `111e76d`; implementation baseline: `f7eefc1`.
- Original workspace remains on `master`, untouched. The earlier working frontend edits were committed upstream before implementation began; only an unrelated untracked `demo.csv` remained.
- The isolated branch was fast-forwarded to the exact committed working version `f7eefc1`, preserving the research documents. This created no new commit and changed nothing in the original checkout or production.

**Baseline protection:** compare redesign changes against `f7eefc1`. Its frontend includes the current `leadCard.js`, tests, Playground and API behavior. Do not copy secrets or databases, edit backend/worker/configuration files, commit another person's work, or advance the baseline again during implementation. The package lock is unchanged; if registry access is unavailable, a separate copy of existing local dependencies may be used only after verifying matching lockfile contents and installed versions.

### Frozen files and behavior

No edits to `backend/`, `voice-agent/`, `domain-configs/`, deployment scripts, infrastructure, environment files, permission settings or repository instructions. Do not alter `frontend/src/api.js` contracts, call payloads, session/auth semantics, billing mutations, polling intervals, campaign lifecycle transitions, consent rules, time windows or concurrency.

Restyling operational components must preserve their handlers, props, component identity, async cleanup, disabled conditions and validation. A visual change is not permission to change a call-flow prompt or "fix" a production backend defect.

## 2. Evidence gathered

Two read-only agents audited frontend architecture and commercial claims. Main-agent code inventory verified the router. Browser Use attempted all ten vendors; seven were readable, two timed out and one was blocked. Research and corrections are in [competitors/README.md](../competitors/README.md) and the [Outpero profile](../competitors/outpero/README.md).

Limitations:
- Browser text/DOM inspection worked; screenshot and pointer actions failed because the native viewport was unattached (0 × 0).
- No competitor authenticated dashboard or actual audio experience was tested.
- Local `http://localhost:3000/landing` navigation returned `ERR_ABORTED`; the local UI has not been visually verified in this pass.
- No tests/builds have run for a redesign because implementation has not begun.
- Operational findings are code/config review, not a fresh production audit.

The previous competitor report overstated missing capabilities and our margin. Outpero already advertises campaigns, captured fields, INR credits, consent, retries and education workflows. Retell markets a complete campaign/QA/analytics workflow. The design should close our usability gaps, not build a claim around features competitors already offer.

## 3. Complete existing page inventory

Source: current working `frontend/src/App.jsx:64-95`; `AuthShell` at lines 50-56. **20 distinct page components, 22 concrete page-route patterns, one legacy redirect and one wildcard fallback.** Login and registration share one component; new/edit share the builder; the two Playground URLs share one component.

| Screen | Route(s) | Access / entry point | Redesign work |
|---|---|---|---|
| Landing | `/` when signed out; `/landing` | Public; signed-in landing redirects home | New message hierarchy, honest example workflow, pricing summary, FAQ, useful navigation |
| Pricing | `/pricing` | Public | Clear allowance/overage/wallet/GST sections; truthful capacity and CTA |
| Roadmap | `/roadmap` | Public | Separate shipped and planned capabilities; avoid commitments presented as live |
| Login / Register | `/login` | Public; two modes | Unified account card, labels, password affordances, actionable errors; respect signup gate |
| Forgot password | `/forgot-password` | Public | Clear submit/sent/error states; accessible fields |
| Reset password | `/reset-password` | Public token flow | Missing/expired token, mismatch, busy and success states |
| Accept invitation | `/accept-invite` | Public token flow | Organization-join explanation, token failures, success; no fake token/session |
| Overview | `/` when signed in | Workspace sidebar | Real usage/status, recent activity, meaningful empty state, next actions |
| Agents | `/agents` | Workspace sidebar | Agent identity, current version, clear Configure/Test actions and empty state |
| Agent workspace | `/agents/:id` | Agent card/list | Consistent tabs, version/history presentation, save feedback and validation |
| Agent builder | `/agents/new`, `/agents/:id/edit` | Agent creation/edit | Six-step progress, accessible forms, review, field errors; preserve version payload |
| Playground | `/playground`, `/playground/:agentVersionId` | Sidebar and agent test actions | Clear voice/text/phone mode differences and permissions; preserve session handlers |
| Campaign list | `/campaigns` | Workspace sidebar | Consistent table/list, statuses, create dialog and no-data state |
| Campaign detail | `/campaigns/:id` | Campaign list | Contacts, import, progress, outcomes and blocked-action explanations; preserve mutations |
| Call history | `/calls` | Workspace sidebar | Clear search/filter/status/type hierarchy; preserve current client-side filtering scope |
| Call detail | `/calls/:id` | Call history/campaign | Outcome and review flags first; extracted fields, transcript, recording, metrics and export |
| Billing & credits | `/credits` | Sidebar/wallet | Distinguish plan allowance from wallet value; payment-disabled/pending/success/failure states |
| Invoice | `/invoices/:id` | Billing invoice list | Print-friendly hierarchy and amounts from API; no invented tax/legal details |
| Platform admin | `/admin` | Platform-admin UI entry | Consistent dense tables/dialogs; retain role visibility and backend permission enforcement |
| Developer tools | `/dev` | Utility link; page checks build-time disable flag | Consistent diagnostics; do not expose new operational controls or secrets |
| Legacy redirect | `/test-call` → `/playground?mode=phone` | Existing saved URLs | Preserve verbatim |
| Not found | `*` | Inside authenticated shell | Useful recovery link; preserve signed-out redirect behavior |

There is no dedicated Settings, Team Management, Privacy, Terms, Refund Policy or Contact page registered in the current router. Existing invitations or role controls do not imply a complete team-settings screen. Do not invent empty settings tabs to make the product look larger.

Potential public legal/contact routes are a separate small addition only after the owner supplies or approves actual business identity, support details and policy text. Draft generic policies must not be represented as legal clearance.

## 4. Approaches and recommendation

| Approach | Benefit | Trade-off | Decision |
|---|---|---|---|
| **Product-led, frontend-only redesign** | Strong visual upgrade, concrete product proof, limited calling regression risk | Does not add missing backend features | **Recommended for this launch** |
| Cinematic/WebGL-heavy marketing site | More visual spectacle | Larger payload, motion/accessibility work, current animation defects; weak answer to onboarding gaps | Defer unless useful after the core experience passes |
| Full platform rebuild plus new integrations | Broader long-term capability | Backend, billing, telephony and schedule risk; violates current protection boundary | Out of scope |

Retain React/Vite and the existing routing/runtime. Do not migrate to Next.js because a competitor uses it. Do not add a second component library or replace LiveKit. New shared components should solve the repeated UI visible here, not form a speculative framework.

## 5. Proposed design

### Brand and visual direction

Working headline: **“Business calls. Clear outcomes.”** Supporting message: configure an agent, run a campaign, review what was learned. Lead with existing capabilities; neither claim fully autonomous enterprise readiness nor restrict every page to colleges.

- Neutral light surfaces, strong dark text, a restrained teal accent; a deliberately designed dark counterpart using the existing theme preference.
- Refined sans-serif hierarchy, readable line lengths, consistent spacing, modest radii and borders, tabular numerals for usage and money.
- Spacious marketing layout; denser, scan-friendly operational tables. One primary action per section, contextual secondary actions.
- Real product imagery only if safely captured and anonymized; otherwise a clearly marked **illustrative example**. Never imply synthetic data is a live customer or a real completed call.
- No invented logos, usage counters, latency numbers, testimonials, security badges or certifications.
- Motion is supplementary: short opacity/transform transitions; respect reduced motion and offscreen/hidden-page state. No animation is required to reveal essential information.
- No mandatory WebGL in the initial release. If a later hero effect is approved, load it after useful content, provide a static fallback, dispose resources, and keep it out of the application bundle.

### Landing page order

1. **Header:** brand, Product/How it works, Use cases, Pricing, Sign in, one honest primary CTA. Accessible mobile navigation.
2. **Hero:** clear outcome, concise audience statement, primary entry and a secondary “See the workflow” anchor. Do not advertise open registration while it is closed.
3. **Product proof:** a short example contact → conversation excerpt → extracted fields → review/export. Label sample data; no “live call” or “interrupt the agent” claim for a scripted animation.
4. **Three-step workflow:** configure agent → prepare and run campaign → review results. Explain consent requirements without claiming certification.
5. **Use cases:** map examples to existing supported configurations; show education as a flagship example alongside other verified use cases. Do not change prompts or create missing backend presets here.
6. **Operator controls:** show existing statuses, pause/review, uncertainty flags and exports, using actual field names available in the API.
7. **Pricing summary:** current list/plan terms, tax treatment and visible link to full details; no unvalidated savings or concurrency promise.
8. **FAQ and footer:** clear support/account path; legal links only when real routes and approved content exist; preserve entry points to working features.

The landing must still redirect signed-in users as before. Public demos must remain non-dialing unless a user separately launches an authorized test.

### Shared application language

- Sidebar and mobile drawer preserve Overview, Agents, Campaigns, Calls, Playground and Billing. Admin visibility remains conditional. Sign out stays reachable on mobile.
- Consistent page titles, breadcrumbs where meaningful, metric labels, content toolbar, empty/error/loading panels, dialogs, tables, tabs, form fields and status badges.
- Buttons communicate action and pending state. Disabled actions explain the real reason: missing version, consent review, outside window, insufficient credit or service failure.
- Missing metrics render as unknown, not zero. Unknown extracted fields remain unknown. Do not relabel calls as successful based on a polished UI.
- Keyboard navigation, visible focus, labelled controls, error announcements, focus restoration, Escape handling, readable contrast and table overflow are part of completion.

### Architecture and safe seams

Use existing `ThemeToggle`, `DataTable`, `Modal`, and `StatusBadge` contracts. Consolidate duplicated public header/footer and CTA presentation after agreeing their visual contract. Keep shared visual tokens in a single owner-controlled layer; public styles must be scoped to avoid existing `.stat-card`/`.conf` collisions.

Do not mass-rewrite the approximately 5,840-line stylesheet before launch. Add/adjust scoped styles, replace the affected public markup deliberately, then remove only confirmed-unused landing code. Preserve functional code during shell changes.

`AgentBuilderPage` serializers/validators and hydration remain unchanged. The create → edit route must preserve wizard state. `PlaygroundPage` must not remount its LiveKit room or change microphone/audio/start/end/finalize behavior during a presentation change. `Layout` keeps its wallet refresh, logout and Outlet identity.

## 6. Confirmed frontend issues to address within scope

- `od-landing.js:314` references `STONE` in the WebGL ring material; the audit found no declaration. Initialization errors are swallowed by the landing effect, risking lost cleanup. Replace/remove this obsolete decorative path as part of the approved landing work, not a call-engine change.
- The scripted landing conversation advertises audio/interruption and shows hardcoded latency/confidence. Replace with truthful, labelled example content or a separately validated real demo; do not silently connect it to calling.
- Reduced-motion CSS can leave example bubbles at zero opacity. Essential content must remain visible without animation.
- Mobile public drawers hidden by opacity/pointer events can remain focusable; add proper visibility semantics and focus handling.
- Console CSS hides the user/sign-out block on narrow screens; retain an obvious account/logout entry.
- Marketing/public and console CSS overlap, and light overrides contain hardcoded contrast conflicts. Verify via actual rendering, not just code review.

Evidence: current `frontend/src/pages/LandingPage.jsx:44-53,287-305`, `frontend/src/od-landing.js:166-259,282-364`, `frontend/src/od-landing.css:32-42`, `frontend/src/components/Layout.jsx:189-227`, `frontend/src/styles.css:3431-3443`.

## 7. Implementation phases and agent ownership

Implementation starts only after design approval. Up to three frontend lanes can run independently after shared tokens/primitives are settled. Shared files have one owner; do not let agents race on global CSS, routes, API utilities or package files.

### Phase 0 — baseline and contract lock

Owner: coordinator/QA.
- Capture the current frontend baseline separately from redesign changes; reconcile dirty-tree differences before editing.
- Record existing test/build results and major bundle sizes.
- Define token/component contracts and fixture-only UI test inputs.
- Review exact scope per agent, including the frozen files above.

Exit: reproducible baseline and attributed diff; no dependency on uncommitted changes is silently lost.

### Phase 1 — foundations and landing

Owner A: shared tokens/primitives and application shell (`Layout`, shared visual components, scoped style layer). Owner B: public pages after token contract (`LandingPage`, `PricingPage`, `RoadmapPage`, public chrome and page-specific styles). Coordinator owns routes and dependency decisions.

Deliver:
- Landing rewrite and removal of misleading scripted-demo claims.
- Pricing/roadmap alignment and functioning account/navigation entry points.
- Consistent light/dark presentation, mobile navigation and nonessential motion.

Exit: public-page browser walkthrough and keyboard checks; no fake working CTA or unsupported claim.

### Phase 2 — all authenticated screens

Owner C: Overview, Agents, Agent Workspace/Builder, Campaign list/detail, Call history/detail. Work in batches: catalogue/setup, then campaign/call operations. Owner A supplies primitives; Owner C uses page-local styles, not shared file edits.

Separate lane after public pages: account/password/invite, Billing/Invoice, Admin/Dev presentation. Keep all mutation and permission behavior unchanged.

Exit: every inventory row has a verified loaded, loading, empty/error and narrow-layout state where applicable. A page is not complete merely because it inherits new colors.

### Phase 3 — regression and preview

Owner: coordinator performs browser work; QA agent may run offline tests/builds and review diffs, but does not dial or use the browser.
- Run fixture-based request/response tests and existing frontend utility tests.
- Browser-check every route, responsive layout, keyboard, both themes and reduced motion.
- Compare outgoing request payloads and button gating with the baseline.
- Inspect network and console failures, route transitions and resource cleanup.
- Review changed-file allowlist before committing explicit paths; do not include unrelated baseline edits.
- Publish a branch preview only after explicit deployment authorization. Never merge or deploy master automatically.

Exit: verified preview and a remaining-blocker list. Production launch requires separate commercial/operational sign-off.

## 8. Test plan and release gates

Commands from isolated `frontend/`, after using the approved runtime and installing the existing lockfile dependencies if necessary:

- `npm test` (currently Node utility tests; not browser coverage).
- `npm run build` (no lint/typecheck script is currently defined).
- `npm run dev -- --host 127.0.0.1 --port 3100 --strictPort` for an isolated frontend preview; do not take over port 3000.

Do not alter backend CORS or running services to make a new UI port work. Use a local fixture-backed test harness for mutation paths or an explicitly approved test backend. Never run production campaign launch, checkout, invite-send or test-call actions as smoke tests.

Browser matrix:
- Public, authenticated and role-limited states.
- Representative widths: 390, 768, 1280 and 1440 CSS pixels; portrait overflow and table scrolling.
- Both themes; reduced motion; keyboard-only menus/dialogs/forms; 200% zoom.
- Missing/expired tokens, failed fetch, 401/402/422, empty lists, absent fields, long agent/campaign names, large rupee values, low balance, payment unavailable.
- Agent create/edit version payloads; wizard state through navigation; campaign confirmation/blocked states; exports using fixtures.
- Playground session lifecycle via isolated mocks/offline tests; no microphone or real dial without explicit authorization.
- Logged-out `/`, protected redirects, `/landing`, public pages, all detail routes, legacy redirect and 404 recovery.
- No serious new console errors or leaked listeners/renderers on repeated route navigation.

Quality targets to measure, not advertise: LCP ≤ 2.5 seconds on a representative throttled mobile run, CLS ≤ 0.1, useful content without WebGL, no significant console-bundle growth from marketing effects, WCAG AA text contrast and visible focus. Record actual results; don't equate a build pass with a browser pass.

**Browser evidence (updated 2026-10-29):** the in-app browser MCP remained unusable (`NATIVE_BROWSER_VIEWPORT_UNAVAILABLE`, viewport 0x0, visible=false, attached=false), so visual QA ran through a local headless Edge CDP harness. It authenticates with the seeded local demo account (`demo@example.com`, local development only) against `localhost:5173` because the backend CORS allowlist does not include 127.0.0.1:3100, and captures full pages plus element crops. 25 shots cover: landing, pricing and roadmap in both themes; 390 px mobile for landing, pricing, roadmap, login, overview (incl. shell drawer); login and forgot-password; overview, campaigns, campaign detail, calls, call detail, agents, agent detail, builder, credits, dev tools and playground; both themes across workspace pages. No page threw a runtime exception during capture. Fixes verified by re-capture include light-theme secondary buttons, status badges, progress track, campaign notice spacing, danger button, agent meta chips, builder step rail, dark segmented control and mobile table scrolling. Remaining open browser gates: 768/1280 widths, 200% zoom, reduced-motion rendering, keyboard-only traversal in a real browser (focus-trap logic is covered by 9 unit tests), simulated 401/402/empty/large-value states, Playground lifecycle with mocks, and measured LCP/CLS. Do not claim those as verified.

## 9. Launch gates outside frontend scope

| Gate | Current evidence | Required before a public paid launch |
|---|---|---|
| Registration | `render.yaml:55-57` defaults public signup to false | Verify live setting; deliberately authorize opening it, or use an invitation-only CTA |
| Payments | Razorpay order/verify/webhook code exists; operational credentials/capture/webhook readiness not checked | Authorized sandbox validation, then separate production payment readiness decision |
| Billing duration/coverage | Code audit flags pre-dial timestamps and competing completion paths | Reproduce in isolated tests and verify connected-time/once-only debiting; no backend edit in this redesign |
| Unit economics | ₹3 includes GST; ₹2.30 cost is an estimate | Reconcile real provider bills, net taxes, gateway fees and plan utilization |
| Concurrency | Plan catalogue 2/2/5/15/50, deployment campaign clamp defaults to 1 per org | Publish only deliverable capacity; separate measured load test before increasing it |
| Legal/tax/privacy | No dedicated legal routes; seller details and operational sign-off unverified | Owner-approved policies/support identity and appropriate legal/tax review |
| Localization/retention claims | Render region is Singapore; retention implementation is not every advertised plan value | Remove unsupported India-only/certification/retention claims or independently validate them |
| Security posture | Previous session reported dependency alerts; not re-audited here | Separate current security review; do not assert they are fixed |

A controlled, invitation-only product preview is the recommended fallback if these gates remain unresolved on 2026-10-29. A polished public landing page can launch separately from self-serve paid calling.

## 10. Approval boundary and completion definition

Approval requested: the product-led visual direction, frontend-only scope, phased coverage of all existing pages, evidence-based copy corrections, isolated development and browser release gates above.

Approval does NOT authorize call-pipeline changes, provider swaps, pricing changes, opening signup, sending calls, changing payment settings, rewriting legal terms as factual, merging master or production deployment.

Complete means the approved frontend scope is implemented and browser-verified on the isolated branch, functional contracts are preserved, research links resolve, and unresolved operational launch gates are plainly reported. Research/design preparation alone is not a completed SaaS redesign.

## 11. Approved implementation contract

**Goal:** replace the inconsistent marketing and console presentation without replacing working product behavior.

**Architecture:** keep React 18, Vite 5, existing route elements, API clients and page state. Coordinator owns global tokens, shell and existing shared primitives; parallel owners use page-local styles and do not edit shared files. No dependency changes, commits, publishing, calls or payment activity.

### Visual interfaces

New `frontend/src/launch.css` loads after the three existing global stylesheets. Consumers use the existing variables: `--bg`, `--surface`, `--surface2`, `--fg`, `--muted`, `--dim`, `--brand`, `--brand-soft`, `--border`, `--danger`, `--success`, `--warn`, `--font-u`, `--font-d`, `--font-m`.

| Role | Light | Dark |
|---|---|---|
| Background | `#f4f7f7` | `#101e1e` |
| Surface | `#ffffff` | `#162827` |
| Text | `#172b2a` | `#eef5f3` |
| Secondary text | `#526967` | `#a3b8b4` |
| Accent | `#0d756c` | `#79d4c4` |
| Border | `#d5e1df` | `#334d49` |

Retain the existing DM Sans font, including display headings; use tabular numerals for money and counts. Left-align the hero headline against a clearly labelled transcript-to-fields example. Use rounded controls but more restrained table surfaces. No decorative gradient wash, metric wall, animated waveform, invented user logos or WebGL. Public pages use `es-public-*`; each operational lane scopes styles under its own page classes. Every essential section remains visible with animation disabled.

### Task A — baseline and shared foundation (coordinator)

Files: `frontend/src/main.jsx`, `launch.css`, `components/Layout.jsx`, `components/Modal.jsx`, `components/DataTable.jsx`, `App.jsx`, `theme.js`, `frontend/index.html`.

- [x] Preserve the current frontend by fast-forwarding the isolated branch to `f7eefc1`.
- [x] Run the existing 30 utility tests; all pass (suite later grew to 43 passing tests).
- [x] Record the baseline build and bundle sizes using verified local dependencies.

  Baseline `f7eefc1` (built from `git archive` with the worktree's existing `node_modules`): index CSS 96.84 kB / 19.08 gzip; index JS 340.58 kB / 101.73 gzip; LandingPage CSS 60.84 kB / 10.85 gzip; LandingPage JS 492.75 kB / 125.70 gzip; Pricing 9.18 kB; Roadmap 10.56 kB; Playground 579.55 kB; xlsx 429.03 kB.

  Redesigned build: index CSS 114.51 kB / 22.33 gzip; index JS 358.18 kB / 105.49 gzip; PublicLayout CSS 22.86 kB / 4.29 gzip; PublicLayout JS 5.30 kB; LandingPage JS 14.69 kB / 4.54 gzip; Pricing 11.95 kB; Roadmap 7.03 kB; DevTools 22.35 kB; Playground 580.36 kB; xlsx 429.03 kB. Landing-route payload falls from ~991 kB raw / 257 kB gzip to ~516 kB raw / 139 kB gzip because the old marketing bundle (492.75 kB) is gone. No Three.js/WebGL chunk exists in either build; the only >500 kB chunks are the pre-existing Playground and xlsx chunks.

- [x] Add tokens and scoped shell/form/table/button/dialog styles without rewriting the original global stylesheet. New files only: `launch.css`, `public-site.css`, `workspace-pages.css`, `account-pages.css`; `styles.css`, `saas.css`, `theme-light.css` untouched.
- [x] Keep `Modal({title, children, onClose, footer, wide})` and `DataTable({columns, rows, rowKey, onRowClick, loading, empty, emptyAction})` signatures; add focus containment/restoration and keyboard row activation without new mutation handlers. Signatures verified at `Modal.jsx:4` and `DataTable.jsx:8`; focus trap in `utils/dialogFocus.js` with 9 passing tests.
- [x] Preserve wallet refresh, role gating, logout and Outlet identity; make every navigation item and signout reachable on mobile. `Layout.jsx` still renders `<Outlet/>`, `clearSession`, and `is_platform_admin` gating; the mobile drawer screenshot shows every nav item plus Sign out.
- [x] Preserve every route; add a recovery link only inside the existing wildcard page. `App.jsx`, `api.js`, `theme.js` and `index.html` are byte-identical to `f7eefc1`.
- [x] Run focused rendered markup and existing utility checks before reviewing the shared diff. 43/43 tests pass.

### Task B — public product journey (public owner)

Files: `frontend/src/pages/LandingPage.jsx`, `PricingPage.jsx`, `RoadmapPage.jsx`, new `components/PublicLayout.jsx`, new `public-site.css`; legacy `od-landing.js`, `od-pricing.js` and their styles may only be removed once all references are confirmed absent.

- [x] Write a coherent shared public header/footer and accessible small-screen navigation. Keep Playground, pricing and account entry points. `PublicLayout.jsx`; at 390 px the menu toggle reports `aria-expanded` correctly (verified via CDP), reveals Product, Use cases, Pricing, Playground, Roadmap and Open workspace, and page width stays 390 with no horizontal overflow.
- [x] Replace landing with the approved headline, clearly labelled synthetic workflow, truthful existing use cases, controls, pricing summary and FAQ.
- [x] Give pricing its current plans, allowance/tax/wallet distinctions and eligibility caveats; do not change prices or invent public signup availability.
- [x] Separate shipped versus planned roadmap items; retain all current working product links. Footer keeps How it works, Use cases, Pricing, Roadmap, Overview, Agents, Agent builder, Campaigns, Call history, Playground, Billing & credits and Sign in.
- [x] Check public markup renders without WebGL, unknown metrics, audio promises or dead links. No WebGL dependency; landing chunk is 14.69 kB. Pricing/roadmap links resolve to existing routes.

### Task C — agent and operations journey (workspace owner)

Files: `frontend/src/pages/OverviewPage.jsx`, `AgentsPage.jsx`, `AgentDetailPage.jsx`, `AgentBuilderPage.jsx`, `CampaignsPage.jsx`, `CampaignDetailPage.jsx`, `CallsIndexPage.jsx`, `CallDetailPage.jsx`, new `workspace-pages.css`.

- [ ] Improve catalogue/setup hierarchy, agent identity, six-step builder navigation and current validation presentation.
- [ ] Preserve builder serializers, hydration and create-to-edit component identity.
- [ ] Improve campaign contact/import/progress layout, blocked-state descriptions and call-history filters without changing payloads or polling.
- [ ] Prioritize structured outcomes, uncertainty and transcript evidence in call detail without inventing values or rewriting extraction logic.
- [ ] Scope page styles so loaded/error/empty layouts and wide tables remain useful at narrow widths.
- [ ] Compare every functional hook, API call, event handler and disabled condition against the baseline.

### Task D — account, billing and utilities (account owner)

Files: `frontend/src/pages/Login.jsx`, `PasswordPages.jsx`, `CreditsPage.jsx`, `InvoicePage.jsx`, `AdminPage.jsx`, `DevToolsPage.jsx`, `PlaygroundPage.jsx`, new `account-pages.css`.

- [ ] Align account cards, labels, errors, token states and public navigation without changing session/auth behavior.
- [ ] Improve plan/wallet/invoice hierarchy and payment-state presentation; keep all values, calculations and payment handlers unchanged.
- [ ] Improve admin/dev density without exposing controls or changing role checks.
- [ ] Adjust only Playground presentation; retain LiveKit identity, effects, media and session actions verbatim.
- [ ] Compare functional code against the baseline and verify invoice print rules.

### Task E — integration and verification (coordinator)

- [x] Run `npm --prefix frontend test` from the isolated root; preserve the 30 baseline utility tests and add focused offline rendering checks. Result: 43/43 pass, including new `presentation.test.js` and `dialogFocus.test.js`.
- [x] Run `npm --prefix frontend run build`; record chunks and verify no marketing Three.js payload. Build succeeds; chunk sizes recorded in Task A. The only chunks over 500 kB are the pre-existing Playground and xlsx bundles; the landing route lost its 492.75 kB chunk.
- [x] Run `npm --prefix frontend run dev -- --host 127.0.0.1 --port 3100 --strictPort`; leave the original services alone. Served on 3100; an additional dev server on `localhost:5173` was needed because backend CORS only allows localhost:3000/5173, and no CORS or service config was changed.
- [ ] Exercise the browser matrix in section 8 without real mutations, using isolated fixture data. Partially done: 25 headless-Edge shots cover both themes, 390/1440 widths, authenticated and public states, drawer, tables and detail routes with no runtime exceptions; remaining gates (768/1280, 200% zoom, reduced motion, keyboard traversal, simulated error/empty states, Playground lifecycle, LCP/CLS) are listed in section 8 and stay open. No real mutations were performed.
- [x] Verify `git diff f7eefc1 -- backend voice-agent domain-configs render.yaml` is empty and inspect every changed path. Diff is empty; every changed path is under `frontend/`, `competitors/` or `docs/`.
- [x] Update this plan with actual test results and unresolved gates. No claim of production readiness without the required evidence.
