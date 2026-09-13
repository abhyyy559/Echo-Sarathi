import React, { useEffect, useRef, useState } from 'react';
import { playgroundApi } from '../api.js';
import LeadCardForm, { ABSENT_STUDENT_DEFAULTS } from './LeadCardForm.jsx';

export function confidenceClass(v) {
  const n = typeof v === 'number' ? v : Number(v);
  if (v == null || Number.isNaN(n)) return '';
  const pct = n <= 1 ? n * 100 : n;
  return pct >= 80 ? 'chip-green' : pct >= 50 ? 'badge-amber' : 'chip-red';
}

/**
 * Reusable TEXT-mode playground session (typed conversation with a saved
 * agent version). Owns the full lifecycle: start session -> opening turn ->
 * reply loop -> complete + report.
 *
 * Extracted from PlaygroundPage so the agent workspace (/agents/:id) can
 * embed the exact same test engine in its "Test agent" panel.
 *
 * Props:
 *   versionId      saved agent version to test (number | numeric string)
 *   onFinishReport complete-session result ({call_id, transcript,
 *                  extracted_fields, latency, outcome, ...}) handed to the
 *                  parent for the full-report view / last-run preview.
 *   autoStart      begin the session as soon as versionId is set (default true)
 *   contact        optional lead-card object passed to startSession; falls back
 *                  to the card edited in the form below (applies on (re)start).
 */
export default function TextPlayground({ versionId, onFinishReport, autoStart = true, contact }) {
  const [messages, setMessages] = useState([]); // [{speaker:'caller'|'agent', text}]
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [done, setDone] = useState(false);
  const [fields, setFields] = useState([]);
  const [completing, setCompleting] = useState(false);
  const [attempt, setAttempt] = useState(0); // bump to retry a failed start
  const [contactCard, setContactCard] = useState(contact || { ...ABSENT_STUDENT_DEFAULTS });

  const sessionRef = useRef(null);
  const logRef = useRef(null);
  const lastReportRef = useRef(null);
  // Mirror so the (re)start effect always reads the latest card without
  // restarting the session on every keystroke.
  const contactRef = useRef(contactCard);
  contactRef.current = contactCard;

  // (Re)start the session whenever the target version changes.
  useEffect(() => {
    lastReportRef.current = null;
    sessionRef.current = null;
    setMessages([]);
    setInput('');
    setError(null);
    setDone(false);
    setFields([]);
    setCompleting(false);
    if (!versionId || !autoStart) return undefined;

    let cancelled = false;
    setBusy(true);
    (async () => {
      try {
        const sess = await playgroundApi.startSession(Number(versionId), contactRef.current);
        if (cancelled) return;
        sessionRef.current = sess;
        const res = await playgroundApi.sendTurn(sess.call_id, { event: 'start' });
        if (cancelled) return;
        applyTurnResponse(res);
      } catch (e) {
        if (!cancelled) setError(e.message || 'Could not start this text test.');
      } finally {
        if (!cancelled) setBusy(false);
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [versionId, autoStart, attempt]);

  // Keep the log pinned to the newest bubble.
  useEffect(() => {
    const el = logRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, busy]);

  function applyTurnResponse(res) {
    if (!res) return;
    if (res.reply_text) {
      setMessages((prev) => [...prev, { speaker: 'agent', text: res.reply_text }]);
    }
    if (Array.isArray(res.extracted_fields) && res.extracted_fields.length > 0) {
      setFields((prev) => {
        const byName = new Map(prev.map((f) => [f.field_name, f]));
        res.extracted_fields.forEach((f) => byName.set(f.field_name, f));
        return Array.from(byName.values());
      });
    }
    if (res.done) setDone(true);
  }

  function sendText(e) {
    e.preventDefault();
    const text = input.trim();
    if (!text || busy || done || !sessionRef.current) return;
    setMessages((prev) => [...prev, { speaker: 'caller', text }]);
    setInput('');
    setBusy(true);
    setError(null);
    playgroundApi
      .sendTurn(sessionRef.current.call_id, { text })
      .then(applyTurnResponse)
      .catch((err) => setError(err.message || 'Could not send that message.'))
      .finally(() => setBusy(false));
  }

  /** Finalize the session; resolves with the report (cached for repeats). */
  async function finish() {
    if (lastReportRef.current) {
      onFinishReport && onFinishReport(lastReportRef.current);
      return lastReportRef.current;
    }
    if (!sessionRef.current) return null;
    setCompleting(true);
    setError(null);
    try {
      const res = await playgroundApi.completeSession(sessionRef.current.call_id);
      lastReportRef.current = res || {};
      onFinishReport && onFinishReport(lastReportRef.current);
      return lastReportRef.current;
    } catch (e) {
      setError(e.message || 'Could not finalize the session.');
      return null;
    } finally {
      setCompleting(false);
    }
  }

  return (
    <div className="text-playground">
      <details className="card" open>
        <summary>Who are we calling? (optional lead card)</summary>
        <LeadCardForm value={contactCard} onChange={setContactCard} defaults={ABSENT_STUDENT_DEFAULTS} />
      </details>
      <div className="form-actions space-between tp-toolbar">
        <span className="meta-line">
          {done ? (
            <span className="text-success">Conversation finished</span>
          ) : busy ? (
            'Agent is thinking…'
          ) : (
            'Type replies below — extraction runs live.'
          )}
        </span>
        <button type="button" className="btn btn-ghost btn-sm" onClick={finish} disabled={completing || !sessionRef.current}>
          {completing ? 'Finishing…' : 'End session & show report'}
        </button>
      </div>

      <div className="chat-log tchat" ref={logRef}>
        {messages.length === 0 && !busy && !error && <p className="hint">Starting the conversation…</p>}
        {messages.map((m, i) => (
          <div key={i} className={`chat-row ${m.speaker === 'caller' ? 'caller' : 'agent'}`}>
            <div className={`chat-bubble ${m.speaker === 'caller' ? 'bubble-caller' : 'bubble-agent'}`}>{m.text}</div>
          </div>
        ))}
        {busy && (
          <div className="chat-row agent">
            <div className="chat-bubble bubble-agent hint">Typing…</div>
          </div>
        )}
      </div>

      {error && (
        <div className="banner banner-error">
          {error}{' '}
          {!sessionRef.current && (
            <button type="button" className="btn btn-secondary btn-sm" onClick={() => setAttempt((a) => a + 1)}>
              Retry
            </button>
          )}
        </div>
      )}

      {done && (
        <div className="banner banner-success">
          <strong>Conversation complete.</strong> The agent ended this session.
        </div>
      )}

      {fields.length > 0 && (
        <div>
          <h3 className="card-title">Extracted so far</h3>
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Field</th>
                  <th>Value</th>
                  <th style={{ width: '130px' }}>Confidence</th>
                </tr>
              </thead>
              <tbody>
                {fields.map((f, i) => (
                  <tr key={`${f.field_name}-${i}`}>
                    <td className="cell-strong">{f.field_name}</td>
                    <td>{f.field_value != null ? String(f.field_value) : '—'}</td>
                    <td>
                      <span className={`badge ${confidenceClass(f.confidence) || 'badge-gray'}`}>
                        {f.confidence != null && !Number.isNaN(Number(f.confidence))
                          ? `${Math.round(Number(f.confidence) <= 1 ? Number(f.confidence) * 100 : Number(f.confidence))}%`
                          : '—'}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {!done ? (
        <form className="chat-input-row" onSubmit={sendText}>
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Type your reply…"
            disabled={busy || !sessionRef.current}
            aria-label="Your message"
          />
          <button type="submit" className="btn btn-primary" disabled={busy || !input.trim() || !sessionRef.current}>
            Send
          </button>
        </form>
      ) : (
        <div className="form-actions">
          <button type="button" className="btn btn-primary" onClick={finish} disabled={completing}>
            {completing ? 'Collecting results…' : 'View full report'}
          </button>
        </div>
      )}
    </div>
  );
}
