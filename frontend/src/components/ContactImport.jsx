import React, { useMemo, useRef, useState } from 'react';
import { api } from '../api.js';
import ColumnMapper, {
  EMPTY_MAPPING,
  guessMapping,
  parseDelimited,
  isValidPhoneValue,
} from './ColumnMapper.jsx';

const MAX_PREVIEW_ROWS = 5;
const MAX_ROWS = 10000; // advisory client-side cap; backend validates the full file

function readFileTable(file) {
  if (/\.(xlsx|xls)$/i.test(file.name)) {
    // Dynamic import keeps the ~400 kB SheetJS bundle out of the initial page load.
    return import('xlsx').then(async (XLSX) => {
      const buf = await file.arrayBuffer();
      const wb = XLSX.read(buf, { type: 'array' });
      const ws = wb.Sheets[wb.SheetNames[0]];
      if (!ws) throw new Error('The workbook has no readable sheet.');
      const table = XLSX.utils.sheet_to_json(ws, { header: 1, raw: false, defval: '' });
      return table.map((row) => (Array.isArray(row) ? row.map((c) => String(c ?? '').trim()) : []));
    });
  }
  return file.text().then((text) => parseDelimited(text));
}

/**
 * Three-step contact import:
 *   1. pick    — drop/select a CSV or Excel file
 *   2. map     — detected headers preview + dropdown mapping (pre-guessed)
 *   3. review  — validity summary + consent + confirm → submit
 *
 * Submits the exact same multipart contract as before:
 *   file, mapping JSON, consent_default.
 */
export default function ContactImport({ campaignId, onImported }) {
  const inputRef = useRef(null);

  const [stage, setStage] = useState('pick'); // 'pick' | 'map' | 'review'
  const [dragOver, setDragOver] = useState(false);
  const [parsing, setParsing] = useState(false);
  const [fileObj, setFileObj] = useState(null);
  const [parsed, setParsed] = useState(null); // { fileName, headers[], rows[][] }
  const [mapping, setMapping] = useState({ ...EMPTY_MAPPING });
  const [customRows, setCustomRows] = useState([]);
  // Checked by default: a roster uploaded by your org (e.g. the college's
  // enrollment list) is the institutional relationship, so these contacts
  // are callable without any extra allowlist. Uncheck only if you are
  // unsure about consent for these numbers.
  const [consentDefault, setConsentDefault] = useState(true);
  const [error, setError] = useState(null);
  const [importing, setImporting] = useState(false);
  const [submitError, setSubmitError] = useState(null);

  function reset() {
    setStage('pick');
    setFileObj(null);
    setParsed(null);
    setMapping({ ...EMPTY_MAPPING });
    setCustomRows([]);
    setError(null);
    setSubmitError(null);
  }

  async function handleFile(f) {
    if (!f) return;
    setError(null);
    setSubmitError(null);
    setParsing(true);
    try {
      const table = await readFileTable(f);
      if (!table || table.length < 2) {
        throw new Error("Couldn't find a header row plus at least one contact row in this file.");
      }
      const headers = table[0].map((h, i) => (h !== '' ? h : `Column ${i + 1}`));
      const rows = table.slice(1).filter((r) => r.some((c) => c !== ''));
      if (rows.length === 0) throw new Error('No data rows found under the header row.');

      setFileObj(f);
      setParsed({
        fileName: f.name,
        headers,
        rows: rows.slice(0, MAX_ROWS),
        truncated: rows.length > MAX_ROWS ? rows.length - MAX_ROWS : 0,
      });
      setMapping(guessMapping(headers));
      setCustomRows([]);
      setStage('map');
    } catch (e) {
      reset();
      setError(e.message || 'Could not read this file.');
    } finally {
      setParsing(false);
    }
  }

  // ---- derived validity stats (phone column only) ----
  const stats = useMemo(() => {
    if (!parsed || !mapping.phone_col || !parsed.headers.includes(mapping.phone_col)) return null;
    const pi = parsed.headers.indexOf(mapping.phone_col);
    let valid = 0;
    let flagged = 0;
    for (const row of parsed.rows) {
      const v = row[pi];
      if (v == null || String(v).trim() === '' || !isValidPhoneValue(v)) flagged++;
      else valid++;
    }
    return { total: parsed.rows.length, valid, flagged };
  }, [parsed, mapping.phone_col]);

  async function doImport() {
    if (!fileObj || !parsed || !mapping.phone_col) return;
    setImporting(true);
    setSubmitError(null);
    const custom = {};
    customRows.forEach((r) => {
      if (r.field && r.col) custom[r.field.trim()] = r.col;
    });
    const fd = new FormData();
    fd.append('file', fileObj);
    fd.append(
      'mapping',
      JSON.stringify({
        name_col: mapping.name_col || null,
        phone_col: mapping.phone_col || null,
        id_col: mapping.id_col || null,
        consent_col: mapping.consent_col || null,
        custom,
      })
    );
    fd.append('consent_default', consentDefault ? 'true' : 'false');
    try {
      const result = await api.importContacts(campaignId, fd);
      reset();
      if (onImported) onImported(result || {});
    } catch (e) {
      setSubmitError(e.message || 'Import failed.');
    } finally {
      setImporting(false);
    }
  }

  const mappedSummary = [
    { label: 'Contact name', value: mapping.name_col },
    { label: 'Phone number', value: mapping.phone_col },
    { label: 'External ID', value: mapping.id_col },
    { label: 'Consent', value: mapping.consent_col },
    ...customRows.filter((r) => r.field && r.col).map((r) => ({ label: r.field.trim(), value: r.col })),
  ];

  return (
    <div className="card upload-panel">
      <h3 className="card-title">Import contacts</h3>

      {stage === 'pick' && (
        <>
          <p className="hint">
            Upload your contact list as CSV or Excel — we read the columns automatically and show you a preview to
            confirm. Nothing is dialed by uploading.
          </p>
          <div
            className={`dropzone${dragOver ? ' drag' : ''}`}
            role="button"
            tabIndex={0}
            aria-label="Choose a CSV or Excel file with your contacts"
            onClick={() => inputRef.current && inputRef.current.click()}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                inputRef.current && inputRef.current.click();
              }
            }}
            onDragOver={(e) => {
              e.preventDefault();
              setDragOver(true);
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragOver(false);
              handleFile(e.dataTransfer.files && e.dataTransfer.files[0]);
            }}
          >
            <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
              <polyline points="17 8 12 3 7 8" />
              <line x1="12" y1="3" x2="12" y2="15" />
            </svg>
            <div className="dropzone-title">
              {parsing ? 'Reading file…' : 'Drop your CSV or Excel file here, or click to browse'}
            </div>
            <div className="dropzone-sub">.csv, .tsv or .xlsx · columns are detected automatically</div>
          </div>
          <input
            ref={inputRef}
            type="file"
            accept=".csv,.tsv,.txt,.xlsx,.xls"
            className="visually-hidden"
            tabIndex={-1}
            onChange={(e) => handleFile(e.target.files && e.target.files[0])}
          />
          {error && <div className="banner banner-error">{error}</div>}
        </>
      )}

      {stage === 'map' && parsed && (
        <>
          <div className="file-chip-row">
            <span className="chip" title={parsed.fileName}>
              📄 {parsed.fileName}
            </span>
            <span className="hint inline-hint">
              {parsed.rows.length} contact row{parsed.rows.length === 1 ? '' : 's'} found
              {parsed.truncated > 0 ? ` · showing the first ${MAX_ROWS}` : ''}
            </span>
            <button type="button" className="btn btn-ghost btn-sm" onClick={reset}>
              Choose a different file
            </button>
          </div>

          <ColumnMapper
            headers={parsed.headers}
            rows={parsed.rows}
            mapping={mapping}
            onMappingChange={setMapping}
            customRows={customRows}
            onCustomRowsChange={setCustomRows}
          />

          {!mapping.phone_col && (
            <p className="hint hint-error">Choose which column holds the phone number to continue.</p>
          )}
          <div className="upload-actions">
            <button type="button" className="btn btn-primary" disabled={!mapping.phone_col} onClick={() => setStage('review')}>
              Continue to review
            </button>
            <button type="button" className="btn btn-secondary" onClick={() => setStage('pick')}>
              Back
            </button>
          </div>
        </>
      )}

      {stage === 'review' && parsed && (
        <>
          <p className="hint">
            Final check before anything is uploaded. Rows whose phone doesn't look like a real number are flagged
            below — they are skipped as invalid at import.
          </p>

          <div className="review-summary-grid">
            <div className="review-block">
              <h4>File</h4>
              <dl>
                <dt>Name</dt>
                <dd>{parsed.fileName}</dd>
                <dt>Contact rows</dt>
                <dd>{parsed.rows.length}</dd>
              </dl>
            </div>
            <div className="review-block">
              <h4>Column mapping</h4>
              <ul className="review-list mapping-recap">
                {mappedSummary.map((m) => (
                  <li key={m.label}>
                    {m.label}: <code>{m.value}</code>
                  </li>
                ))}
                {!mapping.name_col && <li className="text-muted">Contact name: not mapped</li>}
              </ul>
            </div>
            <div className="review-block">
              <h4>Phone check</h4>
              {stats ? (
                <p>
                  <span className="chip chip-green">{stats.valid} look valid</span>{' '}
                  {stats.flagged > 0 && <span className="chip chip-red">{stats.flagged} flagged</span>}
                </p>
              ) : (
                <p className="hint hint-error">No phone column selected.</p>
              )}
            </div>
          </div>

          {stats && stats.flagged > 0 && (
            <div className="banner banner-info">
              {stats.flagged} of {stats.total} rows have missing/invalid phone numbers. Fix them in the file and
              re-import later, or continue — those rows are kept but never called.
            </div>
          )}

          <label className="check-row">
            <input type="checkbox" checked={consentDefault} onChange={(e) => setConsentDefault(e.target.checked)} />
            <span>
              These contacts consented to be called (e.g. your college enrollment roster)
              <span className="hint"> — uncheck if unsure; unchecked rows need a consent column or per-contact consent before they can be dialed</span>
            </span>
          </label>

          {submitError && <div className="banner banner-error">{submitError}</div>}

          <div className="upload-actions">
            <button
              type="button"
              className="btn btn-primary btn-lg"
              disabled={importing || !mapping.phone_col}
              onClick={doImport}
            >
              {importing
                ? 'Importing…'
                : `Confirm & import ${parsed.rows.length} contact${parsed.rows.length === 1 ? '' : 's'}`}
            </button>
            <button type="button" className="btn btn-secondary" disabled={importing} onClick={() => setStage('map')}>
              Back to mapping
            </button>
          </div>
        </>
      )}
    </div>
  );
}
