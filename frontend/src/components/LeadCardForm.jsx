import React from 'react';

/**
 * Pre-filled contact card for testing.
 *
 * These were empty, so every test run began with the operator typing the same
 * student/parent names by hand - pure friction during the verification loop.
 * They are only DEFAULTS for the form: edit any field before starting a
 * session, and the change is used verbatim.
 */
export const ABSENT_STUDENT_DEFAULTS = {
  student_name: 'Abhi',
  parent_name: 'Ram',
  class_section: '10-B',
  absent_date: '',
};

/** Generic key/value lead card ("who are we calling?").
 * Props: {value: object, onChange: (next) => void, defaults?: object}
 */
export default function LeadCardForm({ value, onChange, defaults }) {
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
            placeholder="value"
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
      <p className="hint">Only non-empty values are sent. The agent uses these names instead of asking who it is calling.</p>
    </div>
  );
}
