import React, { useEffect, useRef, useState } from 'react';
import { api } from '../api.js';

/**
 * TestCallPanel — place a real phone call from inside the playground.
 *
 * Previously test calls lived on a separate page, so verifying the phone path
 * meant re-entering the agent version and contact card by hand. This reuses
 * the playground's already-selected version and contact, dials, and then
 * tracks the call live (ringing -> answered -> completed) by polling the call
 * record. The LiveConsole next to it shows the backend events for the same
 * call, so media failures are visible instead of silent.
 */

const POLL_MS = 2500;

export default function TestCallPanel({ versionId, contactCard }) {
  const [to, setTo] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [callId, setCallId] = useState(null);
  const [status, setStatus] = useState(null);
  const timerRef = useRef(null);

  const stopPolling = () => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  };

  useEffect(() => stopPolling, []);

  const poll = async (id) => {
    try {
      const call = await api.getCall(id);
      setStatus(call);
      const terminal = ['completed', 'failed', 'no-answer', 'busy', 'canceled'].includes(call.status);
      if (terminal) stopPolling();
    } catch (e) {
      setError(e.message || 'Could not read call status.');
      stopPolling();
    }
  };

  async function placeCall() {
    setBusy(true);
    setError(null);
    setStatus(null);
    stopPolling();
    const payload = {};
    if (versionId) payload.agent_version_id = Number(versionId);
    const card = Object.fromEntries(
      Object.entries(contactCard || {}).filter(([, v]) => String(v ?? '').trim())
    );
    if (Object.keys(card).length) payload.contact = card;
    const trimmed = to.trim();
    if (trimmed) payload.to = trimmed;
    try {
      const res = await api.placeTestCall(payload);
      const id = res?.call_id ?? res?.id ?? null;
      setCallId(id);
      if (id) {
        timerRef.current = setInterval(() => poll(id), POLL_MS);
        poll(id);
      }
    } catch (e) {
      setError(e.message || 'Could not place test call.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="dp-wrap">
      <div className="dp-head" style={{ cursor: 'default' }}>
        <span className="dp-title">Test call</span>
        <span className="dp-sub">real phone call, same agent + contact as above</span>
      </div>
      <div className="dp-body">
        <div className="field" style={{ marginBottom: 8 }}>
          <label htmlFor="pg-call-to">Dial</label>
          <input
            id="pg-call-to"
            value={to}
            onChange={(e) => setTo(e.target.value)}
            placeholder="+91 98765 43210"
            inputMode="tel"
          />
          <small className="dp-sub" style={{ display: 'block', marginTop: 4 }}>
            Leave blank to dial the configured sandbox number.
          </small>
        </div>
        <button type="button" className="btn btn-primary btn-sm" disabled={busy} onClick={placeCall}>
          {busy ? 'Placing…' : 'Place test call'}
        </button>
        {error && <div className="dp-error" style={{ marginTop: 6 }}>{error}</div>}
        {status && (
          <div style={{ marginTop: 8 }}>
            <div className="dp-member">
              <span className="dp-name">call {status.id ?? callId}</span>
              <span className={String(status.status) === 'completed' ? 'dp-ok' : ''}>{status.status}</span>
              {status.to_number && <span className="dp-cap">{status.to_number}</span>}
            </div>
            {status.provider_call_id && (
              <div className="dp-cap" style={{ marginTop: 2 }}>provider: {status.provider_call_id}</div>
            )}
          </div>
        )}
        {!status && !error && (
          <div className="dp-cap" style={{ marginTop: 6 }}>
            Dials through Vobiz. Watch the live console below for answer, media and hangup events.
          </div>
        )}
      </div>
    </div>
  );
}
