import React, { useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { authApi, setSession } from '../api.js';

/* Forgot / reset / accept-invite — the three emailed token flows. They share
 * one centred card so the whole auth surface feels like the login screen. */

function BrandMark() {
  return (
    <div className="logo-row auth-logo-row">
      <div className="mark">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M2 12h2l3-8 4 16 4-12 3 6h4" />
        </svg>
      </div>
      <b>Echo Sarathi</b>
    </div>
  );
}

function AuthShell({ title, sub, children }) {
  return (
    <div className="auth-screen">
      <div className="auth-card">
        <BrandMark />
        <h1 className="auth-title">{title}</h1>
        <p className="auth-sub">{sub}</p>
        {children}
        <div className="auth-back">
          <Link className="btn btn-ghost btn-sm" to="/login">
            ← Back to sign in
          </Link>
        </div>
      </div>
    </div>
  );
}

function ErrorBox({ message }) {
  return <div className={`err-msg${message ? ' show' : ''}`}>{message}</div>;
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
        <div className="banner banner-info" style={{ marginTop: 8 }}>
          Nothing arrived? Check spam, or write to hello@echosarathi.ai.
        </div>
      </AuthShell>
    );
  }

  return (
    <AuthShell
      title="Reset your password"
      sub="Enter the email you sign in with and we'll send a one-time link."
    >
      <form onSubmit={submit}>
        <div className="field">
          <label htmlFor="forgot-email">
            Email <span className="req-star">*</span>
          </label>
          <input
            id="forgot-email"
            type="email"
            autoComplete="email"
            autoFocus
            value={email}
            placeholder="you@company.com"
            onChange={(e) => setEmail(e.target.value)}
          />
        </div>
        <ErrorBox message={error} />
        <button type="submit" className="cta-btn" disabled={busy || !email.trim()}>
          <span className="spin" style={busy ? { display: 'inline-block' } : {}} />
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
    <form onSubmit={submit}>
      <div className="field">
        <label htmlFor="new-password">
          New password <span className="req-star">*</span>
        </label>
        <input
          id="new-password"
          type="password"
          autoComplete="new-password"
          autoFocus
          value={password}
          placeholder="Minimum 8 characters"
          onChange={(e) => setPassword(e.target.value)}
        />
      </div>
      <div className="field">
        <label htmlFor="confirm-password">
          Confirm password <span className="req-star">*</span>
        </label>
        <input
          id="confirm-password"
          type="password"
          autoComplete="new-password"
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
        <span className="spin" style={busy ? { display: 'inline-block' } : {}} />
        {busy ? 'Please wait…' : submitLabel}
      </button>
      {!token && (
        <p className="hint hint-error" style={{ marginTop: 14 }}>
          This page needs the link from your email — the token is missing.
        </p>
      )}
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
