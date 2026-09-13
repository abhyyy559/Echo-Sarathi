# Login Page — Match OpenDesign Reference

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Update Login.jsx JSX/class names and styles.css to match the OpenDesign `login.html` reference, preserving all existing React functionality (auth API, mode switching, form validation, redirect).

**Architecture:** Two-file change: rewrite the JSX tree inside `Login.jsx` to use OpenDesign class names/structure (logo-row, cta-btn, err, demo-hint, legal, etc.), and append new CSS rules to `styles.css` for the animated SVG logo mark. No new files, no new dependencies.

**Tech Stack:** React 18, react-router-dom, existing CSS custom properties.

## Global Constraints

- All existing authApi.login / authApi.register calls must keep working exactly as before.
- The `navigate(from)` redirect must remain.
- Mode switching between login/register must remain.
- Do not add authentication/authorization work.
- Do not hardcode API keys.
- All CSS variables (`--brand`, `--muted`, `--dim`, `--line2`, `--gold`, `--font-d`, `--font-m`, etc.) already exist in `:root` — use them.

## Files

| File | Action |
|---|---|
| `frontend/src/pages/Login.jsx` | Modify — rewrite JSX tree, class names, add logo SVG |
| `frontend/src/styles.css` | Modify — append new rules after existing login section (~line 1821) |

---

### Task 1: Update Login.jsx JSX to match OpenDesign

**Files:**
- Modify: `frontend/src/pages/Login.jsx:59-193` (the return block)

**What changes (preserving all functionality):**

1. Replace `.auth-brand` div with `.logo-row` div containing the SVG logo mark, square icon with `<span class="mark">`, and `<b>Echo Sarathi</b>`.
2. Add `<h1 id="formTitle">` and `<p class="sub">` after the logo row (update dynamically on mode switch).
3. Replace `.banner.banner-error` with `.err-msg.show` div.
4. Replace `.auth-demo-hint` with `.demo-hint` — update credentials to `demo@echosarathi.ai` / `voice1234`.
5. Replace `btn btn-primary btn-block` submit button with `.cta-btn` pattern (spinner + text span).
6. Replace `.auth-legal` with `.legal`.
7. Replace `.login-brand-side` with `.brand-side`.
8. Replace `.login-lang-line` with `.lang-line`.
9. Update mode switching to dynamically change formTitle/formSub/goTxt text content (via state or conditional rendering).
10. **Keep** `authApi.login`, `authApi.register`, `setSession`, `navigate(from)`, mode switching, wave bars — all unchanged.

```jsx
// Step 1 — Full replacement for the return() block in Login.jsx
// The outer function signature, state, and handlers stay EXACTLY as they are.
// Only the JSX inside return() changes.
return (
  <div className="login-split">
    {/* ---- Left side: form ---- */}
    <div className="form-side">
      <div className="logo-row">
        <svg className="logo-mark" width="38" height="22" viewBox="0 0 46 26" fill="none" aria-hidden="true">
          <circle className="lm-src" cx="6" cy="13" r="2.2"/>
          <path className="lm-a l1" d="M10.02 7.27 A7 7 0 0 1 10.02 18.73"/>
          <path className="lm-a l2" d="M12.88 3.17 A12 12 0 0 1 12.88 22.83"/>
          <circle className="lm-echo" cx="40" cy="13" r="2.2"/>
          <path className="lm-b r1" d="M35.98 7.27 A7 7 0 0 0 35.98 18.73"/>
          <path className="lm-b r2" d="M33.12 3.17 A12 12 0 0 0 33.12 22.83"/>
        </svg>
        <span className="mark">
          <svg width="20" height="20" viewBox="0 0 32 32">
            <path d="M6 16v0M11 8v16M16 4v24M21 10v12M26 13v6"
              stroke="#e9e4da" strokeWidth="3" strokeLinecap="round"/>
          </svg>
        </span>
        <b>Echo Sarathi</b>
      </div>

      <h1>{isRegister ? 'Create your workspace' : 'Welcome back'}</h1>
      <p className="sub">
        {isRegister
          ? 'Set up your organization and start calling in minutes.'
          : 'Sign in to your voice console.'}
      </p>

      <div className="mode-tabs">
        <button type="button" className={!isRegister ? 'on' : ''} onClick={() => switchMode('login')}>
          Sign in
        </button>
        <button type="button" className={isRegister ? 'on' : ''} onClick={() => switchMode('register')}>
          Create account
        </button>
      </div>

      {isRegister && (
        <div>
          <label htmlFor="login-org">Organization name</label>
          <input
            id="login-org"
            type="text"
            placeholder="e.g. Sunrise Academy"
            autoComplete="organization"
            value={form.orgName}
            onChange={(e) => setForm({ ...form, orgName: e.target.value })}
          />
        </div>
      )}

      <label htmlFor="login-email">Email</label>
      <input
        id="login-email"
        type="email"
        placeholder="you@school.edu"
        autoComplete="email"
        value={form.email}
        onChange={(e) => setForm({ ...form, email: e.target.value })}
      />

      <label htmlFor="login-password">Password</label>
      <input
        id="login-password"
        type="password"
        placeholder={isRegister ? 'Minimum 8 characters' : 'Minimum 8 characters'}
        autoComplete={isRegister ? 'new-password' : 'current-password'}
        value={form.password}
        onChange={(e) => setForm({ ...form, password: e.target.value })}
      />

      {error && <div className="err-msg show">{error}</div>}

      <div className="demo-hint">
        Demo environment — try <b>demo@echosarathi.ai</b> / <b>voice1234</b>
      </div>

      <button
        type="submit"
        className="cta-btn"
        disabled={
          busy ||
          !form.email.trim() ||
          !form.password ||
          (isRegister && !form.orgName.trim())
        }
      >
        <span className="spin" style={{ display: busy ? 'inline-block' : 'none' }} />
        <span>{busy ? 'Please wait…' : isRegister ? 'Create account' : 'Sign in to console'}</span>
      </button>

      <p className="legal">By continuing you agree to the Terms of Service and Privacy Policy.</p>

      <p className="lang-line">
        English today · <b>తెలుగు next</b> · code-switching on the roadmap
      </p>
    </div>

    {/* ---- Right side: brand panel ---- */}
    <div className="brand-side">
      <div className="bwave">
        {waveBars.map((bar, i) => (
          <i
            key={i}
            style={{
              '--h': `${bar.height}%`,
              animationDelay: `${bar.delay}s`,
            }}
          />
        ))}
      </div>
      <h2>Build AI voice agents that <em>talk to your customers</em>.</h2>
      <p>
        Create an agent once, test it in the browser, then launch outbound campaigns
        that call real people — and return every conversation as clean, structured results.
      </p>
      <p className="lang-line">
        English today · <b>తెలుగు next</b> · code-switching on the roadmap
      </p>
    </div>
  </div>
);
```

- [ ] **Step 1: Read Login.jsx**

```bash
# Confirm file contents
cat frontend/src/pages/Login.jsx
```

- [ ] **Step 2: Replace the return() block**

Replace everything inside the `return (...)` in Login.jsx with the JSX above. Keep the function signature, all state declarations, and all handler functions (switchMode, submit, waveBars) exactly as they are.

- [ ] **Step 3: Verify the component still imports correctly**

Run: `cd frontend && npx vite build 2>&1 | head -30`
Expected: Build succeeds with no errors (warnings are ok).

---

### Task 2: Append logo SVG animation CSS to styles.css

**Files:**
- Modify: `frontend/src/styles.css` — insert after the `.login-split .mode-tabs button.on` block (after line 1821), before the `.sidebar-user` section.

**New CSS to insert:**

```css
/* Logo mark SVG animations */
.logo-mark { flex: none; }
.lm-src { fill: #8f867a; }
.lm-a { fill: none; stroke: #8f867a; stroke-width: 2; stroke-linecap: round; }
.lm-b { fill: none; stroke: #ece7dd; stroke-width: 2; stroke-linecap: round; filter: drop-shadow(0 0 4px rgba(233,228,218,.45)); }
.lm-echo { fill: #ece7dd; filter: drop-shadow(0 0 5px rgba(233,228,218,.6)); }
.l1, .l2, .r1, .r2 { animation: lmPulse 2.8s ease-in-out infinite; }
.l2 { animation-delay: .16s; }
.r1 { animation-delay: .5s; }
.r2 { animation-delay: .66s; }
@keyframes lmPulse { 0% { opacity: .14; } 18% { opacity: 1; } 55% { opacity: .85; } 100% { opacity: .12; } }
@media (prefers-reduced-motion: reduce) { .l1, .l2, .r1, .r2 { animation: none; opacity: .75; } }

/* Login page — logo row */
.logo-row { display: flex; align-items: center; gap: 11px; margin-bottom: 40px; }
.logo-row b { font-family: var(--font-d); font-size: 18px; font-weight: 500; font-style: italic; }

/* Login page — form heading */
.form-side h1 { font-family: var(--font-d); font-size: 27px; font-weight: 600; margin-bottom: 6px; }
.form-side .sub { color: var(--muted); font-size: 14px; margin-bottom: 28px; }

/* CTA button */
.cta-btn {
  width: 100%; margin-top: 26px; background: var(--brand); color: #1a140a;
  border: none; border-radius: 11px; padding: 13px; font-size: 15px;
  font-weight: 700; font-family: inherit; cursor: pointer;
  display: flex; align-items: center; justify-content: center; gap: 10px;
  transition: .2s;
}
.cta-btn:hover { filter: brightness(1.08); box-shadow: 0 8px 30px rgba(233,228,218,.25); }
.cta-btn:disabled { opacity: 0.5; cursor: not-allowed; }

/* Spinner inside cta-btn */
.spin {
  width: 16px; height: 16px; border: 2px solid rgba(26,20,10,.3);
  border-top-color: #1a140a; border-radius: 50%;
  animation: sp .7s linear infinite; display: none;
}
@keyframes sp { to { transform: rotate(360deg); } }

/* Error message */
.err-msg {
  display: none; background: rgba(224,110,95,.09);
  border: 1px solid rgba(224,110,95,.35); color: #eec4b8;
  border-radius: 10px; padding: 11px 14px; font-size: 13.5px; margin-top: 18px;
}
.err-msg.show { display: block; }

/* Legal text */
.legal { margin-top: 26px; font-size: 12px; color: var(--dim); text-align: center; }

/* Demo hint — override for login split form */
.login-split .demo-hint {
  margin-top: 20px; border: 1px dashed var(--line2);
  border-radius: 10px; padding: 12px 14px; font-size: 12.5px;
  color: var(--dim); line-height: 1.7;
}
.login-split .demo-hint b {
  color: var(--muted); font-family: var(--font-m); font-weight: 400; font-size: 12px;
}

/* Login lang-line inside form-side */
.login-split .form-side .lang-line {
  margin-top: 40px; font-size: 13px; color: var(--dim); letter-spacing: .06em;
}
.login-split .form-side .lang-line b { color: var(--gold); font-weight: 500; }

/* Brand-side heading override for .brand-side (not .login-brand-side) */
.login-split .brand-side { composes: /* no change to existing .login-brand-side rules */; }
```

- [ ] **Step 4: Insert CSS rules into styles.css**

Insert the block above after line 1821 (after `.login-split .mode-tabs button.on { ... }`) and before the `.sidebar-user` section.

- [ ] **Step 5: Verify build**

Run: `cd frontend && npx vite build 2>&1 | head -30`
Expected: Build succeeds with no errors.

---

### Task 3: Update class names in other components that reference login classes (if any)

**Files:**
- Search: `frontend/src/` for references to old class names that may break

**Old class names removed from Login.jsx:**
- `.auth-brand` → `.logo-row`
- `.brand-mark` → (removed — replaced by `.logo-row` children)
- `.brand-name` → (removed — replaced by `<b>`)
- `.login-brand-side` → `.brand-side`
- `.login-lang-line` → `.lang-line`
- `.banner.banner-error` → `.err-msg`
- `.auth-legal` → `.legal`
- `.auth-demo-hint` → `.demo-hint`
- `.form-actions` → (removed — `.cta-btn` handles its own spacing)

- [ ] **Step 6: Search for stale references**

Run: `rg "auth-brand|brand-mark|brand-name|login-brand-side|login-lang-line|banner-error|auth-legal|auth-demo-hint|form-actions" frontend/src/ --include "*.jsx" --include "*.js" --include "*.css"`
Expected: No references outside of Login.jsx and styles.css (where old rules can be left as dead CSS without harm, or cleaned up).

- [ ] **Step 7: Clean up dead CSS rules in styles.css (optional)**

Remove or comment out old rules for `.auth-brand`, `.brand-mark`, `.brand-name`, `.login-brand-side`, `.login-lang-line`, `.auth-legal`, `.auth-demo-hint`, `.auth-back`, `.form-actions` if they are no longer referenced anywhere.

- [ ] **Step 8: Final build verification**

Run: `cd frontend && npx vite build 2>&1`
Expected: Clean build, zero errors.

---

### Task 4: Visual verification

- [ ] **Step 9: Start dev server and verify**

Run: `cd frontend && npm run dev`
Open `http://localhost:5173/login` (or wherever it runs) and verify:
1. Logo row shows animated sound wave SVG + square icon + "Echo Sarathi" italic text
2. Form title says "Welcome back" / "Sign in to your voice console."
3. Mode tabs switch between Sign in / Create account, title/subtitle update
4. Demo hint shows `demo@echosarathi.ai` / `voice1234`
5. Error messages appear in red rounded box
6. Submit button has spinner animation on load
7. Legal text visible below button
8. Right panel shows wave animation, headline, lang-line
9. Login with valid credentials navigates to `/`
10. Error state shows error message correctly
