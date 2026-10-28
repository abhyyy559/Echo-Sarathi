import React, { useEffect, useRef, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { apiTargetLabel, authApi, setSession } from '../api.js';

const GOOGLE_CLIENT_ID = String(import.meta.env.VITE_GOOGLE_CLIENT_ID || '').trim();

export default function Login() {
  const navigate = useNavigate();
  const location = useLocation();
  const from = location.state && location.state.from ? location.state.from : '/';

  // Landing-page "Register" CTAs deep-link into the register tab.
  const [mode, setMode] = useState(location.state && location.state.mode === 'register' ? 'register' : 'login');
  const [form, setForm] = useState({ orgName: '', email: '', password: '' });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const googleBtnRef = useRef(null);
  const [googleReady, setGoogleReady] = useState(false);

  const isRegister = mode === 'register';
  // The offline mock session is a local-development convenience only. In a
  // deployed build it must never mint a fake token: every API call would then
  // 401 and the "demo" would look like a broken product.
  const ALLOW_OFFLINE_DEMO =
    import.meta.env.DEV && import.meta.env.VITE_ALLOW_OFFLINE_DEMO === 'true';

  function switchMode(next) {
    setMode(next);
    setError(null);
  }

  // The public demo account is configured at build time (Vercel env vars), not
  // hardcoded here. Login always goes through the real API with whatever the
  // visitor typed, so a stale password shows the backend's error instead of a
  // misleading "demo account is not available" banner. Empty vars = no hint.
  const DEMO_EMAIL = (import.meta.env.VITE_DEMO_EMAIL || '').trim();
  const DEMO_PASSWORD = import.meta.env.VITE_DEMO_PASSWORD || '';
  const showDemoHint = Boolean(DEMO_EMAIL && DEMO_PASSWORD);
  const usesDemoCredentials =
    !isRegister &&
    showDemoHint &&
    form.email.trim() === DEMO_EMAIL &&
    form.password === DEMO_PASSWORD;

  function fillDemo() {
    setForm({ orgName: '', email: DEMO_EMAIL, password: DEMO_PASSWORD });
    setError(null);
  }

  async function completeGoogleSignIn(credential) {
    setBusy(true);
    setError(null);
    try {
      const res = await authApi.googleLogin(credential);
      if (!res || !res.token) {
        throw new Error(
          `The backend at ${apiTargetLabel()} did not return a session token. Check the API deployment and database migrations.`
        );
      }
      setSession(res.token, res.user);
      navigate(from, { replace: true });
    } catch (err) {
      setError(err.message || 'Google sign-in failed. Please try again.');
    } finally {
      setBusy(false);
    }
  }

  // Google Identity Services renders its own button. The script is only
  // loaded when a client id was baked into the build (VITE_GOOGLE_CLIENT_ID).
  useEffect(() => {
    if (!GOOGLE_CLIENT_ID) return undefined;
    let cancelled = false;

    function mountButton() {
      const target = googleBtnRef.current;
      if (cancelled || !target || !window.google?.accounts?.id) return;
      window.google.accounts.id.initialize({
        client_id: GOOGLE_CLIENT_ID,
        callback: (response) => {
          if (response && response.credential) {
            completeGoogleSignIn(response.credential);
          }
        },
      });
      const width = Math.max(200, Math.min(360, Math.floor(target.clientWidth || 360)));
      target.innerHTML = '';
      window.google.accounts.id.renderButton(target, {
        type: 'standard',
        theme: 'outline',
        size: 'large',
        shape: 'rectangular',
        text: 'continue_with',
        logo_alignment: 'left',
        width,
      });
      setGoogleReady(true);
    }

    if (window.google?.accounts?.id) {
      mountButton();
      return () => {
        cancelled = true;
      };
    }

    const existing = document.getElementById('google-identity-services');
    if (existing) {
      existing.addEventListener('load', mountButton);
      return () => {
        cancelled = true;
        existing.removeEventListener('load', mountButton);
      };
    }

    const script = document.createElement('script');
    script.id = 'google-identity-services';
    script.src = 'https://accounts.google.com/gsi/client';
    script.async = true;
    script.defer = true;
    script.addEventListener('load', mountButton);
    document.head.appendChild(script);
    return () => {
      cancelled = true;
      script.removeEventListener('load', mountButton);
    };
  }, []);

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = isRegister
        ? await authApi.register({
            orgName: form.orgName.trim(),
            email: form.email.trim(),
            password: form.password,
          })
        : await authApi.login({ email: form.email.trim(), password: form.password });
      if (!res || !res.token) {
        throw new Error(
          `The backend at ${apiTargetLabel()} did not return a session token. Check the API deployment and database migrations.`
        );
      }
      setSession(res.token, res.user);
      navigate(from, { replace: true });
    } catch (err) {
      // Dev-only escape hatch: with the API down, keep the offline mock usable.
      if (usesDemoCredentials && ALLOW_OFFLINE_DEMO) {
        setSession('demo-token', { email: form.email.trim(), role: 'admin' });
        navigate(from, { replace: true });
        return;
      }
      setError(
        err.message ||
          `Could not sign in. Check that the backend at ${apiTargetLabel()} is reachable.`
      );
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

        {GOOGLE_CLIENT_ID && <div className="google-auth" ref={googleBtnRef} />}
        {googleReady && (
          <div className="auth-divider">
            <span>or use your email</span>
          </div>
        )}

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

        {!isRegister && (
          <div className="field-foot">
            <Link to="/forgot-password">Forgot password?</Link>
          </div>
        )}

        <div className={`err-msg${error ? ' show' : ''}`}>{error}</div>

        {!isRegister && showDemoHint && (
          <button type="button" className="demo-hint demo-hint-btn" onClick={fillDemo}>
            Demo — use <b>{DEMO_EMAIL}</b> / <b>{DEMO_PASSWORD}</b>
            <span className="demo-hint-do">click to fill</span>
          </button>
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
