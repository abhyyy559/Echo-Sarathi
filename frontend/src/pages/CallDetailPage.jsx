import React, { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { API_BASE, callExportUrl } from '../api.js';
import usePoll from '../hooks/usePoll.js';
import { resolveCallActivity } from '../utils/callActivity.js';
import { cleanTranscriptText } from '../utils/transcript.js';

const TERMINAL_STATUSES = new Set(['completed', 'failed', 'no_answer', 'busy', 'canceled', 'cancelled', 'invalid']);

const AGENT_SPEAKERS = new Set(['agent', 'ai', 'bot', 'assistant', 'system', 'voice_agent']);

function speakerIsAgent(speaker) {
  return AGENT_SPEAKERS.has(String(speaker || '').toLowerCase());
}

function fmtDateTime(value) {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  return d.toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

function fmtDuration(seconds) {
  if (seconds == null || Number.isNaN(Number(seconds))) return '—';
  const s = Math.max(0, Math.round(Number(seconds)));
  const m = Math.floor(s / 60);
  return `${m}:${String(s % 60).padStart(2, '0')}`;
}

function fmtSeconds(value) {
  if (value == null || value === '' || Number.isNaN(Number(value))) return '—';
  return `${Number(value).toLocaleString(undefined, { maximumFractionDigits: 3 })} s`;
}

function fmtClock(value) {
  if (value == null) return null;
  if (typeof value === 'number' || /^\d+(\.\d+)?$/.test(String(value))) {
    const s = Math.max(0, Math.round(Number(value)));
    return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
  }
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  return d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function fmtNum(value, maxFractionDigits = 4) {
  const n = Number(value);
  if (value == null || Number.isNaN(n)) return '—';
  return n.toLocaleString(undefined, { maximumFractionDigits: maxFractionDigits });
}

function titleCase(s) {
  return String(s)
    .replace(/[_-]+/g, ' ')
    .replace(/\b\w/g, (ch) => ch.toUpperCase());
}

function confChipClass(value) {
  if (value == null || value === '') return '';
  const num = Number(value);
  const pct = num <= 1 ? num * 100 : num;
  return pct >= 85 ? 'hi' : 'md';
}

function resolveUrl(url) {
  if (!url) return null;
  if (/^https?:\/\//i.test(url)) return url;
  return `${API_BASE}${url.startsWith('/') ? '' : '/'}${url}`;
}

export default function CallDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [isLive, setIsLive] = useState(true);
  const [playing, setPlaying] = useState(false);

  const { data: call, error, loading, reload } = usePoll(`/api/calls/${id}`, 3000, isLive);

  useEffect(() => {
    if (call && call.status && TERMINAL_STATUSES.has(call.status)) setIsLive(false);
  }, [call]);

  if (error && !call) {
    return (
      <div>
        <button className="btn btn-ghost" onClick={() => navigate(-1)}>
          ← Back
        </button>
        <div className="banner banner-error">
          {error}{' '}
          <button className="btn btn-secondary btn-sm" onClick={reload}>
            Retry
          </button>
        </div>
      </div>
    );
  }

  if (loading && !call) {
    return (
      <div className="loading-page">
        <span className="spinner" /> Loading call…
      </div>
    );
  }

  if (!call) return null;

  const live = call.status && !TERMINAL_STATUSES.has(call.status);
  const callActivity = resolveCallActivity(call);
  const pickupToFirstAudio = call.pickup_to_first_audio_seconds;
  const openingDuration = call.opening_duration_seconds;
  const transcript = call.transcript || [];
  const extracted = call.extracted_fields || [];
  const recordingUrl = resolveUrl(call.recording_url);

  const latencyEntries = call.latency ? Object.entries(call.latency) : [];
  const e2eMs = call.latency?.e2e ?? call.latency?.total ?? call.latency?.end_to_end ?? null;
  const durationSec = call.duration_seconds;

  const metaLine = [
    call.started_at ? `Started ${fmtDateTime(call.started_at)}` : null,
    durationSec != null ? `duration ${fmtDuration(durationSec)}` : null,
    e2eMs != null ? `median E2E ${fmtNum(e2eMs, 0)} ms` : null,
  ]
    .filter(Boolean)
    .join(' · ');

  return (
    <div className="call-detail">
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <button className="btn btn-ghost" onClick={() => navigate(-1)}>
          ← Back
        </button>
        <div className="export-group" style={{ marginLeft: 'auto' }}>
          <span className="export-label">Export:</span>
          <button
            className="btn btn-secondary btn-sm"
            onClick={() => window.open(callExportUrl(id, 'csv'), '_blank')}
          >
            CSV
          </button>
          <button
            className="btn btn-secondary btn-sm"
            onClick={() => window.open(callExportUrl(id, 'xlsx'), '_blank')}
          >
            XLSX
          </button>
        </div>
      </div>

      {error && <div className="banner banner-error">{error}</div>}

      {call.flagged_for_human && (
        <div className="banner gold">⚑ Escalated — needs human follow-up.</div>
      )}

      <section className="card pad" aria-labelledby="call-activity-title">
        <div
          role="status"
          aria-live="polite"
          aria-atomic="true"
          style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}
        >
          <h3 id="call-activity-title" style={{ fontFamily: 'var(--font-d)', fontSize: 15 }}>
            Call activity
          </h3>
          <span className="badge badge-blue" style={{ fontSize: 14, padding: '7px 14px' }}>
            {callActivity.label}
          </span>
          <span style={{ color: 'var(--muted)', fontSize: 13 }}>{callActivity.detail}</span>
        </div>
        {(pickupToFirstAudio != null || openingDuration != null) && (
          <dl
            aria-label="Call timing"
            style={{ display: 'flex', gap: 24, flexWrap: 'wrap', margin: '16px 0 0' }}
          >
            {pickupToFirstAudio != null && (
              <div>
                <dt style={{ color: 'var(--muted)', fontSize: 12 }}>Pickup to first audio</dt>
                <dd className="mono" style={{ margin: '3px 0 0', color: 'var(--fg)' }}>
                  {fmtSeconds(pickupToFirstAudio)}
                </dd>
              </div>
            )}
            {openingDuration != null && (
              <div>
                <dt style={{ color: 'var(--muted)', fontSize: 12 }}>Opening duration</dt>
                <dd className="mono" style={{ margin: '3px 0 0', color: 'var(--fg)' }}>
                  {fmtSeconds(openingDuration)}
                </dd>
              </div>
            )}
          </dl>
        )}
      </section>

      <div className="detail">
        {/* Left column */}
        <div>
          <div className="card">
            <div className="card-h">
              <h3>Transcript</h3>
              <span>auto-punctuated · speaker-labeled</span>
            </div>
            <div style={{ padding: 20 }} className="turns">
              {transcript.length === 0 ? (
                <p className="hint">
                  No transcript{live ? ' yet — turns appear here as the call progresses.' : ' available.'}
                </p>
              ) : (
                transcript.map((t, i) => {
                  const agent = speakerIsAgent(t.speaker);
                  const clock = fmtClock(t.timestamp);
                  const label = agent
                    ? 'SARATI AGENT'
                    : titleCase(t.speaker || 'CALLER');
                  return (
                    <div
                      key={t.turn_index != null ? `turn-${t.turn_index}` : i}
                      id={`turn-${t.turn_index != null ? t.turn_index : i}`}
                      className={`trow ${agent ? 'agent' : 'caller'}`}
                    >
                      <span className="meta">
                        {label}
                        {clock ? ` · ${clock}` : ''}
                      </span>
                      <div className="tbubble">{cleanTranscriptText(t.text)}</div>
                    </div>
                  );
                })
              )}
            </div>
          </div>

          {recordingUrl && (
            <div className="recplayer">
              <button
                className="btn sm primary"
                onClick={() => {
                  const audio = document.getElementById('call-audio');
                  if (!audio) return;
                  if (playing) {
                    audio.pause();
                  } else {
                    audio.play();
                  }
                  setPlaying(!playing);
                }}
              >
                {playing ? '❚❚ Pause' : '▶ Play recording'}
              </button>
              <div className="rtrack">
                <div className="rfill" />
              </div>
              <span className="mono" style={{ fontSize: 12, color: 'var(--muted)' }}>
                {fmtDuration(durationSec)}
              </span>
              <audio id="call-audio" preload="none" src={recordingUrl} onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)} />
            </div>
          )}

          {latencyEntries.length > 0 && (
            <div className="card" style={{ marginTop: 18 }}>
              <div className="card-h">
                <h3>Latency per turn</h3>
                <span>ticks at 900 / 1500 ms</span>
              </div>
              <div style={{ padding: 20 }}>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                  {latencyEntries.map(([key, val]) => {
                    const ms = Number(val);
                    if (Number.isNaN(ms)) return null;
                    const color = ms > 1500 ? 'var(--red)' : ms > 900 ? 'var(--amber)' : 'var(--green)';
                    const barH = Math.min(100, (ms / 1800) * 100);
                    return (
                      <div key={key}>
                        <div className="latmeta">
                          <span>{titleCase(key)}</span>
                          <span style={{ fontFamily: 'var(--font-m)', color }}>
                            {fmtNum(ms, 0)} ms
                          </span>
                        </div>
                        <div className="gbar">
                          <b style={{ height: `${barH}%` }} title={`${titleCase(key)} ${ms}ms`} />
                        </div>
                      </div>
                    );
                  })}
                </div>
                <div className="legend">
                  <span><i style={{ background: 'var(--brand)' }} />STT</span>
                  <span><i style={{ background: 'var(--cyan)' }} />LLM</span>
                  <span><i style={{ background: 'var(--gold)' }} />TTS</span>
                  <span><i style={{ background: 'rgba(148, 163, 205, .45)' }} />E2E total</span>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Right column */}
        <div>
          <div className="card pad">
            <h3 style={{ fontFamily: 'var(--font-d)', fontSize: 15 }}>Extracted information</h3>
            <div style={{ marginTop: 10 }}>
              {extracted.length === 0 ? (
                <p className="hint">
                  No structured fields were extracted during this call.
                  {live ? ' The agent collects fields during calls; check the transcript for what it has asked so far.' : ' The agent collects fields during calls; check the transcript for what it asked.'}
                </p>
              ) : (
                extracted.map((f, i) => {
                  const chipCls = confChipClass(f.confidence);
                  const pct =
                    f.confidence != null
                      ? Math.round(Number(f.confidence) <= 1 ? Number(f.confidence) * 100 : Number(f.confidence))
                      : null;
                  return (
                    <div key={f.field_name != null ? `${f.field_name}-${i}` : i} className="frow2">
                      <span className="k">{f.field_name}</span>
                      <span>
                        {f.field_value != null ? String(f.field_value) : '—'}
                        {pct != null && (
                          <span className={`confchip ${chipCls}`}>{pct}%</span>
                        )}
                      </span>
                    </div>
                  );
                })
              )}
            </div>
          </div>

          <div className="card pad" style={{ marginTop: 18 }}>
            <h3 style={{ fontFamily: 'var(--font-d)', fontSize: 15 }}>AI summary</h3>
            {call.summary ? (
              <>
                <p style={{ fontSize: 14, color: 'var(--muted)', lineHeight: 1.7, marginTop: 10 }}>{call.summary}</p>
                {call.outcome && (
                  <div style={{ marginTop: 14 }}>
                    <span className="outcome-tag">Outcome · {String(call.outcome)}</span>
                  </div>
                )}
              </>
            ) : (
              <p className="hint">No summary yet{live ? ' — appears when the call completes.' : '.'}</p>
            )}
            {metaLine && (
              <div style={{ marginTop: 16, fontSize: 12, color: 'var(--dim)' }}>{metaLine}</div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
