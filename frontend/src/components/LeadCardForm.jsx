import React from 'react';

/** Generic key/value lead card ("who are we calling?").
 *
 * `defaults` is the per-agent prefill from src/utils/leadCard.js - the fields
 * that agent's own script asks about, so a clinic is never handed
 * student_name rows. `hints` maps a field key to the value box placeholder.
 *
 * Props: {value: object, onChange: (next) => void, defaults?: object, hints?: object}
 */
export default function LeadCardForm({ value, onChange, defaults, hints }) {
  const rows = Object.entries(value || {});
  const set = (next) => onChange(next);

  function updateRow(index, key, val) {
    const entries = Object.entries(value || {});
    entries[index] = [key, val];
    const next = {};
    for (const [k, v] of entries) {
      if (String(k).trim()) next[String(k).trim()] = v;
    }
    set(next);
  }

  function removeRow(index) {
    const entries = Object.entries(value || {});
    entries.splice(index, 1);
    set(Object.fromEntries(entries));
  }

  function addRow() {
    set({ ...(value || {}), [`field_${rows.length + 1}`]: '' });
  }

  function loadDefaults() {
    set({ ...(defaults || {}) });
  }

  return (
    <div className="lead-card">
      {rows.map(([k, v], i) => (
        <div className="field" key={i}>
          <input
            type="text"
            aria-label="Field name"
            value={k}
            placeholder="field name"
            onChange={(e) => updateRow(i, e.target.value, v)}
          />
          <input
            type="text"
            aria-label="Field value"
            value={v}
            placeholder={hints?.[k] || 'value'}
            onChange={(e) => updateRow(i, k, e.target.value)}
          />
          <button type="button" className="btn btn-secondary btn-sm" onClick={() => removeRow(i)}>
            Remove
          </button>
        </div>
      ))}
      <div className="form-actions">
        <button type="button" className="btn btn-secondary btn-sm" onClick={addRow}>
          Add field
        </button>
        {defaults && (
          <button type="button" className="btn btn-secondary btn-sm" onClick={loadDefaults}>
            Reset defaults
          </button>
        )}
      </div>
      <p className="hint">Prefilled with the fields this agent's script asks about. Only non-empty values are sent, and the agent uses them instead of asking who it is calling.</p>
    </div>
  );
}
