import React from 'react';

// Speech-to-speech targets (NFR-1): median <= 900ms, P95 <= 1500ms.
export const TARGET_MEDIAN_MS = 900;
export const TARGET_P95_MS = 1500;
const BAR_SCALE_MAX_MS = 2000; // bar width denominator

export const METRICS = [
  { key: 'stt_final_ms', label: 'STT final', color: '#2563eb', desc: 'Speech recognition' },
  { key: 'llm_first_token_ms', label: 'LLM first token', color: '#7c3aed', desc: 'Reasoning start' },
  { key: 'tts_first_audio_ms', label: 'TTS first audio', color: '#16a34a', desc: 'Voice synthesis' },
  { key: 'e2e_ms', label: 'End-to-end', color: '#d97706', desc: 'Caller-perceived total' },
];

function fmtMs(v) {
  if (v == null || Number.isNaN(Number(v))) return null;
  return `${Math.round(Number(v))} ms`;
}

/**
 * Latency panel for a finished playground session.
 *
 * turns:   per-turn latency rows from the complete-session response
 * summary: { [metric]: { n, avg, p50, p95 } } | undefined
 *
 * The API returns one row per transcript line, so a turn appears twice: the
 * caller row carries STT timing and the agent row carries LLM/TTS timing plus
 * the serving provider. Rendering both produces duplicate "#N" rows and puts
 * a model label on caller speech. Group by turn_index instead: caller STT +
 * agent reply in one row, "Served by" only where a model actually spoke.
 */
function groupTurns(rows) {
  const byTurn = new Map();
  for (const t of rows) {
    const key = t.turn_index != null ? t.turn_index : `row-${byTurn.size}`;
    if (!byTurn.has(key)) byTurn.set(key, { turn_index: t.turn_index });
    const g = byTurn.get(key);
    const isAgent = String(t.speaker || '').toLowerCase() !== 'caller';
    for (const m of METRICS) {
      if (g[m.key] == null && t[m.key] != null) g[m.key] = t[m.key];
    }
    // The provider belongs to the reply, never to caller speech.
    if (isAgent && g.served_by == null && t.served_by != null) g.served_by = t.served_by;
  }
  return [...byTurn.values()];
}

export default function LatencyPanel({ turns, summary }) {
  const list = groupTurns(Array.isArray(turns) ? turns : []);
  const hasTurns = list.some((t) => METRICS.some((m) => t[m.key] != null));

  return (
    <div className="latency-panel">
      <p className="hint">
        How fast the agent replies after you stop speaking. Targets: median ≤ {TARGET_MEDIAN_MS} ms, worst 5% of turns
        ≤ {TARGET_P95_MS} ms.
      </p>

      {summary && Object.keys(summary).length > 0 && (
        <div className="latency-summary">
          {METRICS.filter((m) => summary[m.key]).map((m) => {
            const s = summary[m.key];
            const e2e = m.key === 'e2e_ms';
            const medianOk = !e2e || s.p50 <= TARGET_MEDIAN_MS;
            const p95Ok = !e2e || s.p95 <= TARGET_P95_MS;
            return (
              <div key={m.key} className="latency-summary-chip" style={{ borderColor: m.color }}>
                <div className="latency-summary-title" style={{ color: m.color }}>
                  {m.label}
                </div>
                <div className="latency-summary-nums">
                  <span>
                    n={s.n}
                  </span>
                  <span>avg {fmtMs(s.avg)}</span>
                  <span className={medianOk ? '' : 'latency-miss'}>
                    p50 {fmtMs(s.p50)}
                  </span>
                  <span className={p95Ok ? '' : 'latency-miss'}>
                    p95 {fmtMs(s.p95)}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {!hasTurns && (!summary || Object.keys(summary).length === 0) ? (
        <p className="hint">No latency measurements were recorded for this session.</p>
      ) : (
        <div className="latency-turns">
          <table className="data-table latency-table">
            <thead>
              <tr>
                <th>Turn</th>
                {METRICS.map((m) => (
                  <th key={m.key}>
                    <span className="latency-key" style={{ backgroundColor: m.color }} aria-hidden="true" />
                    {m.label}
                  </th>
                ))}
                <th>Served by</th>
              </tr>
            </thead>
            <tbody>
              {list
                .filter((t) => METRICS.some((m) => t[m.key] != null))
                .map((t, i) => (
                  <tr key={t.turn_index != null ? t.turn_index : i}>
                    <td className="nowrap cell-strong">#{t.turn_index != null ? t.turn_index : i + 1}</td>
                    {METRICS.map((m) => {
                      const v = t[m.key];
                      if (v == null) {
                        return (
                          <td key={m.key}>
                            <span className="text-muted">—</span>
                          </td>
                        );
                      }
                      const pct = Math.min(100, (Number(v) / BAR_SCALE_MAX_MS) * 100);
                      const over = m.key === 'e2e_ms' && Number(v) > TARGET_P95_MS;
                      return (
                        <td key={m.key}>
                          <div
                            className="latency-bar"
                            title={`${m.label}: ${Math.round(Number(v))} ms${m.key === 'e2e_ms' ? ` (target ${TARGET_MEDIAN_MS}/${TARGET_P95_MS} ms)` : ''}`}
                          >
                            <div
                              className={`latency-fill${over ? ' over' : ''}`}
                              style={{ width: `${pct}%`, backgroundColor: m.color }}
                            />
                            <span
                              className="latency-target-tick"
                              style={{ left: `${(TARGET_MEDIAN_MS / BAR_SCALE_MAX_MS) * 100}%` }}
                              aria-hidden="true"
                            />
                          </div>
                          <span className={`latency-val${over ? ' latency-miss' : ''}`}>{fmtMs(v)}</span>
                        </td>
                      );
                    })}
                    <td className="nowrap cell-strong">
                      {/* Which model actually produced this reply. Failover is
                          invisible without it, and a suspiciously fast answer
                          from an unnamed model is not verifiable. */}
                      {t.served_by?.model || t.served_by?.provider || (
                        <span className="text-muted">—</span>
                      )}
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
          <p className="hint">
            The thin tick on each bar marks the {TARGET_MEDIAN_MS} ms target. End-to-end bars past{' '}
            {TARGET_P95_MS} ms are highlighted red.
          </p>
        </div>
      )}
    </div>
  );
}
