import React, { useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { authApi, setSession } from '../api.js';

export default function Login() {
  const navigate = useNavigate();
  const location = useLocation();
  const from = location.state && location.state.from ? location.state.from : '/';

  // Landing-page "Register" CTAs deep-link into the register tab.
  const [mode, setMode] = useState(location.state && location.state.mode === 'register' ? 'register' : 'login');
  const [form, setForm] = useState({ orgName: '', email: '', password: '' });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const isRegister = mode === 'register';

  function switchMode(next) {
    setMode(next);
    setError(null);
  }

  // Demo logins try the REAL backend account first (seeded by
  // backend/scripts/seed_demo.py), so the dashboard and all APIs work with a
  // genuine JWT. Only when the backend is down or unseeded do we fall back to
  // an offline mock session — api.js knows mock tokens and won't kick a demo
  // user back to /login on 401s; pages render their own error states instead.
  const DEMO_LOGINS = [
    { email: 'demo@example.com', password: 'demo1234' },
    { email: 'demo@echosarathi.ai', password: 'voice1234' },
  ];

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const isDemo =
        !isRegister &&
        DEMO_LOGINS.some((d) => form.email.trim() === d.email && form.password === d.password);
      if (isDemo) {
        try {
          const demoRes = await authApi.login({ email: 'demo@example.com', password: 'demo1234' });
          if (demoRes && demoRes.token) {
            setSession(demoRes.token, demoRes.user);
            navigate(from, { replace: true });
            return;
          }
          throw new Error('no token');
        } catch {
          setSession('demo-token', { email: form.email.trim(), role: 'admin' });
          navigate(from, { replace: true });
          return;
        }
      }
      const res = isRegister
        ? await authApi.register({
            orgName: form.orgName.trim(),
            email: form.email.trim(),
            password: form.password,
          })
        : await authApi.login({ email: form.email.trim(), password: form.password });
      if (!res || !res.token) {
        throw new Error('Server did not return a session token. ' +
          'Make sure the backend (FastAPI) is running at http://localhost:8000');
      }
      setSession(res.token, res.user);
      navigate(from, { replace: true });
    } catch (err) {
      setError(err.message || 'Could not sign in. Is the backend running at http://localhost:8000?');
    } finally {
      setBusy(false);
    }
  }

  // Pre-generate wave bar heights for the brand panel
  const waveBars = React.useMemo(() => {
    const bars = [];
    for (let i = 0; i < 34; i++) {
      bars.push({
        height: 25 + Math.random() * 70,
        delay: Math.random() * -2.4,
      });
    }
    return bars;
  }, []);

  return (
    <div className="login-split">
      {/* ---- Left side: form ---- */}
      <div className="form-side">
        <div className="logo-row">
          <svg className="logo-mark" width="42" height="42" viewBox="0 0 42 42" fill="none" aria-hidden="true">
            <rect x="1" y="1" width="40" height="40" rx="11" className="lm-src" stroke="rgba(143,134,122,.35)" strokeWidth="1"/>
            <path d="M14 26V16" className="lm-a l1" strokeWidth="2.2" strokeLinecap="round"/>
            <path d="M18 26V14" className="lm-a l2" strokeWidth="2.2" strokeLinecap="round"/>
            <path d="M22 26V18" className="lm-b l1" strokeWidth="2.2" strokeLinecap="round"/>
            <path d="M26 26V14" className="lm-echo" strokeWidth="2.2" strokeLinecap="round"/>
            <path d="M30 26V16" className="lm-a r1" strokeWidth="2.2" strokeLinecap="round"/>
            <path d="M34 26V19" className="lm-b r2" strokeWidth="2.2" strokeLinecap="round"/>
          </svg>
          <div className="mark">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M2 12h2l3-8 4 16 4-12 3 6h4" />
            </svg>
          </div>
          <b>Echo Sarathi</b>
        </div>

        <h1>Welcome back</h1>
        <p className="sub">Sign in to your voice console.</p>

        <div className="mode-tabs">
          <button
            type="button"
            className={!isRegister ? 'on' : ''}
            onClick={() => switchMode('login')}
          >
            Sign in
          </button>
          <button
            type="button"
            className={isRegister ? 'on' : ''}
            onClick={() => switchMode('register')}
          >
            Create account
          </button>
        </div>

        <form onSubmit={submit}>
        {isRegister && (
          <div className="field">
            <label htmlFor="login-org">
              Organization name <span className="req-star">*</span>
            </label>
            <input
              id="login-org"
              type="text"
              autoComplete="organization"
              autoFocus
              value={form.orgName}
              placeholder="e.g. Sunrise Academy"
              onChange={(e) => setForm({ ...form, orgName: e.target.value })}
            />
          </div>
        )}

        <div className="field">
          <label htmlFor="login-email">
            Email <span className="req-star">*</span>
          </label>
          <input
            id="login-email"
            type="email"
            autoComplete="email"
            value={form.email}
            placeholder="you@school.edu"
            onChange={(e) => setForm({ ...form, email: e.target.value })}
          />
        </div>

        <div className="field">
          <label htmlFor="login-password">
            Password <span className="req-star">*</span>
          </label>
          <input
            id="login-password"
            type="password"
            autoComplete={isRegister ? 'new-password' : 'current-password'}
            value={form.password}
            placeholder={isRegister ? 'Minimum 8 characters' : 'Your password'}
            onChange={(e) => setForm({ ...form, password: e.target.value })}
          />
        </div>

        <div className={`err-msg${error ? ' show' : ''}`}>{error}</div>

        {!isRegister && (
          <div className="demo-hint">
            Demo — use <b>demo@example.com</b> / <b>demo1234</b> (full data when the backend is seeded)
          </div>
        )}

        <div className="form-actions">
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
            <span className={`spin${busy ? '' : ''}`} style={busy ? { display: 'inline-block' } : {}} />
            {busy ? 'Please wait…' : isRegister ? 'Create account' : 'Sign in to console'}
          </button>
        </div>
        </form>

        <p className="legal">By continuing you agree to the Terms of Service and Privacy Policy.</p>

        <div className="auth-back">
          <Link className="btn btn-ghost btn-sm" to="/">
            ← Back to home
          </Link>
        </div>
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
        <h2>
          Build AI voice agents that <em>talk to your customers</em>.
        </h2>
        <p>
          Create an agent once, test it in the browser, then launch outbound campaigns that call real people — and return every conversation as clean, structured results.
        </p>
        <p className="lang-line">
          English today · <b>తెలుగు next</b> · code-switching on the roadmap
        </p>
      </div>
    </div>
  );
}
