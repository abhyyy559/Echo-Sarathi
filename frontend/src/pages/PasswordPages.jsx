import React, { useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { authApi, setSession } from '../api.js';
import '../account-pages.css';

/* Forgot / reset / accept-invite — the three emailed token flows. They share
 * one centred card so the whole auth surface feels like the login screen. */

function BrandMark() {
  return (
    <Link className="es-account-brand" to="/">Echo Sarathi<span>Voice workspace</span></Link>
  );
}

function AuthShell({ title, sub, children }) {
  return (
    <main className="es-account es-account-auth es-account-password">
      <header className="es-account-public-head">
        <BrandMark />
        <nav aria-label="Account navigation"><Link to="/">Back to home</Link></nav>
      </header>
      <section className="es-account-auth-card" aria-labelledby="account-title">
        <div className="es-account-eyebrow">Account access</div>
        <h1 id="account-title">{title}</h1>
        <p className="es-account-intro">{sub}</p>
        {children}
        <div className="es-account-auth-foot">
          <Link className="es-account-text-link" to="/login">← Back to sign in</Link>
        </div>
      </section>
      <p className="es-account-password-foot">Use the email link for the account or workspace you want to access.</p>
    </main>
  );
}

function ErrorBox({ message }) {
  return <div id="account-form-error" role="alert" className={`err-msg${message ? ' show' : ''}`}>{message}</div>;
}

export function ForgotPasswordPage() {
  const [email, setEmail] = useState('');
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState(null);

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await authApi.forgotPassword(email.trim());
      setSent(true);
    } catch (err) {
      setError(err.message || 'Could not send the reset link.');
    } finally {
      setBusy(false);
    }
  }

  if (sent) {
    return (
      <AuthShell
        title="Check your inbox"
        sub={`If ${email.trim()} has an account, a reset link is on its way. The link is valid for 30 minutes.`}
      >
        <div className="banner banner-info" role="status">
          <strong>Next, open your email.</strong> Check your spam folder if the message has not arrived. You can return to sign in to request another link.
        </div>
      </AuthShell>
    );
  }

  return (
    <AuthShell
      title="Reset your password"
      sub="Enter the email you sign in with and we'll send a one-time link."
    >
      <form onSubmit={submit} aria-busy={busy} aria-describedby="account-form-error">
        <div className="field">
          <label htmlFor="forgot-email">
            Email <span className="req-star" aria-hidden="true">*</span>
          </label>
          <input
            id="forgot-email"
            type="email"
            autoComplete="email"
            autoFocus
            aria-required="true"
            value={email}
            placeholder="you@company.com"
            onChange={(e) => setEmail(e.target.value)}
          />
        </div>
        <ErrorBox message={error} />
        <button type="submit" className="cta-btn" disabled={busy || !email.trim()}>
          <span className="spin" style={busy ? { display: 'inline-block' } : {}} aria-hidden="true" />
          {busy ? 'Sending…' : 'Send reset link'}
        </button>
      </form>
    </AuthShell>
  );
}

function PasswordForm({ token, onSuccess, submitLabel }) {
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function submit(e) {
    e.preventDefault();
    if (password !== confirm) {
      setError('The two passwords do not match.');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await onSuccess(password);
    } catch (err) {
      setError(err.message || 'Something went wrong. Request a new link and try again.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} aria-busy={busy} aria-describedby="account-form-error account-link-help">
      <div className="field">
        <label htmlFor="new-password">
          New password <span className="req-star" aria-hidden="true">*</span>
        </label>
        <input
          id="new-password"
          type="password"
          autoComplete="new-password"
          autoFocus
          aria-required="true"
          aria-describedby="password-requirements"
          value={password}
          placeholder="Minimum 8 characters"
          onChange={(e) => setPassword(e.target.value)}
        />
        <p className="hint" id="password-requirements">Use at least 8 characters, then enter the same password below.</p>
      </div>
      <div className="field">
        <label htmlFor="confirm-password">
          Confirm password <span className="req-star" aria-hidden="true">*</span>
        </label>
        <input
          id="confirm-password"
          type="password"
          autoComplete="new-password"
          aria-required="true"
          aria-describedby="account-form-error"
          value={confirm}
          placeholder="Type it again"
          onChange={(e) => setConfirm(e.target.value)}
        />
      </div>
      <ErrorBox message={error} />
      <button
        type="submit"
        className="cta-btn"
        disabled={busy || !token || password.length < 8 || !confirm}
      >
        <span className="spin" style={busy ? { display: 'inline-block' } : {}} aria-hidden="true" />
        {busy ? 'Please wait…' : submitLabel}
      </button>
      {!token && (
        <p className="banner banner-error" role="alert">
          <strong>Email link required.</strong> The token is missing. Open the complete link from your reset or invitation email.
        </p>
      )}
      <p className="hint" id="account-link-help">Link expired or already used? Request a new password reset, or ask your workspace administrator to resend the invitation.</p>
    </form>
  );
}

export function ResetPasswordPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const token = params.get('token') || '';
  const [done, setDone] = useState(false);

  if (done) {
    return (
      <AuthShell title="Password updated" sub="Use your new password to sign in.">
        <button type="button" className="cta-btn" onClick={() => navigate('/login')}>
          Go to sign in
        </button>
      </AuthShell>
    );
  }

  return (
    <AuthShell title="Choose a new password" sub="This link can only be used once.">
      <PasswordForm
        token={token}
        submitLabel="Update password"
        onSuccess={async (password) => {
          await authApi.resetPassword({ token, password });
          setDone(true);
        }}
      />
    </AuthShell>
  );
}

export function AcceptInvitePage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const token = params.get('token') || '';

  return (
    <AuthShell
      title="Join your team"
      sub="Set a password and you'll be signed straight into the workspace you were invited to."
    >
      <PasswordForm
        token={token}
        submitLabel="Accept invitation"
        onSuccess={async (password) => {
          const res = await authApi.acceptInvite({ token, password });
          if (!res || !res.token) {
            throw new Error('The backend did not return a session — ask your admin to resend the invite.');
          }
          setSession(res.token, res.user);
          navigate('/', { replace: true });
        }}
      />
    </AuthShell>
  );
}
