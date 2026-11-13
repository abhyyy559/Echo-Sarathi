import React, { useEffect, useRef, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { apiTargetLabel, authApi, setSession } from '../api.js';
import '../account-pages.css';

const RAW_GOOGLE_CLIENT_ID = String(import.meta.env.VITE_GOOGLE_CLIENT_ID || '').trim();

// Google only serves a consent card for a Web client id shaped like
// "<project-number>-<hash>.apps.googleusercontent.com". A placeholder such as
// "test-client-id..." loads a blank popup, so treat it as unconfigured.
const GOOGLE_CLIENT_ID = /^\d+-[a-z0-9_-]+\.apps\.googleusercontent\.com$/i.test(
  RAW_GOOGLE_CLIENT_ID
)
  ? RAW_GOOGLE_CLIENT_ID
  : '';
const GOOGLE_CLIENT_ID_INVALID = Boolean(RAW_GOOGLE_CLIENT_ID) && !GOOGLE_CLIENT_ID;

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
    <main className="es-account es-account-auth es-account-login">
      <header className="es-account-public-head">
        <Link className="es-account-brand" to="/">Echo Sarathi<span>Voice workspace</span></Link>
        <nav aria-label="Account navigation">
          <Link to="/pricing">Pricing</Link>
          <Link to="/">Back to home</Link>
        </nav>
      </header>

      <div className="es-account-auth-grid">
        <section className="es-account-auth-card" aria-labelledby="login-title">
          <div className="es-account-eyebrow">Your workspace</div>
          <h1 id="login-title">{isRegister ? 'Create your account' : 'Welcome back'}</h1>
          <p className="es-account-intro">
            {isRegister ? 'Set up an organization when registration is enabled.' : 'Sign in to manage agents, campaigns and call results.'}
          </p>

          <div className="es-account-mode" role="group" aria-label="Account access">
            <button
              type="button"
              className={!isRegister ? 'on' : ''}
              aria-pressed={!isRegister}
              onClick={() => switchMode('login')}
            >
              Sign in
            </button>
            <button
              type="button"
              className={isRegister ? 'on' : ''}
              aria-pressed={isRegister}
              onClick={() => switchMode('register')}
            >
              Create account
            </button>
          </div>

          {isRegister && (
            <p className="es-account-note" id="registration-note">
              Account creation is subject to availability. If registration is closed, use the invitation link provided by your workspace administrator.
            </p>
          )}
          {GOOGLE_CLIENT_ID && <div className="es-account-google" ref={googleBtnRef} />}
          {GOOGLE_CLIENT_ID_INVALID && import.meta.env.DEV && (
            <div className="es-account-note">
              Google sign-in is disabled: <b>VITE_GOOGLE_CLIENT_ID</b> holds a placeholder. Put a
              real client id from Google Cloud Console in <b>frontend/.env.local</b> and restart the
              dev server. Email sign-in still works.
            </div>
          )}
          {googleReady && <div className="es-account-divider">or continue with email</div>}

          <form onSubmit={submit} aria-busy={busy} aria-describedby={isRegister ? 'registration-note login-error' : 'login-error'}>
            {isRegister && (
              <div className="field">
                <label htmlFor="login-org">Organization name <span className="req-star" aria-hidden="true">*</span></label>
                <input
                  id="login-org"
                  type="text"
                  autoComplete="organization"
                  autoFocus
                  aria-required="true"
                  value={form.orgName}
                  placeholder="Your organization"
                  onChange={(e) => setForm({ ...form, orgName: e.target.value })}
                />
              </div>
            )}
            <div className="field">
              <label htmlFor="login-email">Email <span className="req-star" aria-hidden="true">*</span></label>
              <input
                id="login-email"
                type="email"
                autoComplete="email"
                aria-required="true"
                value={form.email}
                placeholder="you@company.com"
                onChange={(e) => setForm({ ...form, email: e.target.value })}
              />
            </div>
            <div className="field">
              <label htmlFor="login-password">Password <span className="req-star" aria-hidden="true">*</span></label>
              <input
                id="login-password"
                type="password"
                autoComplete={isRegister ? 'new-password' : 'current-password'}
                aria-required="true"
                aria-describedby={isRegister ? 'login-password-hint' : undefined}
                value={form.password}
                placeholder={isRegister ? 'Minimum 8 characters' : 'Your password'}
                onChange={(e) => setForm({ ...form, password: e.target.value })}
              />
              {isRegister && <p className="hint" id="login-password-hint">Use at least 8 characters.</p>}
            </div>
            {!isRegister && <div className="field-foot"><Link to="/forgot-password">Forgot password?</Link></div>}
            <div id="login-error" role="alert" className={`err-msg${error ? ' show' : ''}`}>{error}</div>

            {!isRegister && showDemoHint && (
              <button type="button" className="es-account-demo" onClick={fillDemo}>
                <strong>Use the configured demo account</strong>
                <span>{DEMO_EMAIL} · Fill sign-in details</span>
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
                <span className={`spin${busy ? '' : ''}`} style={busy ? { display: 'inline-block' } : {}} aria-hidden="true" />
                {busy ? 'Please wait…' : isRegister ? 'Create account' : 'Sign in to workspace'}
              </button>
            </div>
          </form>
          <p className="es-account-auth-foot">Have an invitation? Open the link in your invitation email to join the right workspace.</p>
        </section>

        <aside className="es-account-story">
          <div className="es-account-eyebrow">From conversation to context</div>
          <h2>Business calls.<br />Clear outcomes.</h2>
          <p>One workspace to configure your agents, prepare outreach and review what each conversation learned.</p>
          <ol className="es-account-steps">
            <li><span>01</span><div><h3>Configure an agent</h3><p>Define the questions and information you need to collect.</p></div></li>
            <li><span>02</span><div><h3>Test before outreach</h3><p>Explore a saved version in the browser Playground.</p></div></li>
            <li><span>03</span><div><h3>Review the results</h3><p>Read transcripts and extracted fields, including what needs human review.</p></div></li>
          </ol>
          <Link to="/playground" className="es-account-text-link">Open Playground →</Link>
        </aside>
      </div>
    </main>
  );
}
