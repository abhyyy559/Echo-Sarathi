import React, { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { agentsApi } from '../api.js';
import ContextFieldsEditor from '../components/ContextFieldsEditor.jsx';
import QuestionFlowEditor from '../components/QuestionFlowEditor.jsx';
import ExtractionSchemaEditor from '../components/ExtractionSchemaEditor.jsx';
import VoiceSettingsForm from '../components/VoiceSettingsForm.jsx';
import {
  buildVersionPayload,
  validateVersionPayload,
  hydrateFromVersion,
  emptyConfig,
} from './AgentBuilderPage.jsx';

const TABS = [
  { key: 'context', label: 'Context' },
  { key: 'flow', label: 'Flow' },
  { key: 'extraction', label: 'Extraction' },
  { key: 'voice', label: 'Voice & Model' },
];

/** Which tab owns each validation-error key prefix. */
function tabForErrorKey(key) {
  if (['system_prompt', 'company_context', 'disclosure_script', 'escalation_rules'].includes(key)) return 'context';
  if (key.startsWith('question_flow')) return 'flow';
  if (key.startsWith('extraction_schema')) return 'extraction';
  if (key.startsWith('voice_settings')) return 'voice';
  return null;
}

/**
 * Agent workspace — /agents/:id.
 *
 * Two-column layout: LEFT is a tabbed config editor (drafting the NEXT
 * immutable version), RIGHT is version history with test buttons.
 */
export default function AgentDetailPage() {
  const params = useParams();
  const routeId = Number(params.id);
  const navigate = useNavigate();

  // ---- loaded data ----
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(null);
  const [agent, setAgent] = useState(null);
  const [versions, setVersions] = useState([]);

  // ---- draft config (next immutable version) ----
  const [config, setConfig] = useState(emptyConfig());
  const [activeTab, setActiveTab] = useState('context');
  const [dirty, setDirty] = useState(false);

  // ---- save ----
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState(null);
  const [generalErrors, setGeneralErrors] = useState([]);
  const [fieldErrors, setFieldErrors] = useState({});
  const [savedVersion, setSavedVersion] = useState(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setLoadError(null);
    (async () => {
      try {
        const a = await agentsApi.get(routeId);
        if (cancelled) return;
        setAgent(a);
        let cfg = emptyConfig();
        if (a.current_version_id != null) {
          try {
            const v = await agentsApi.getVersion(a.current_version_id);
            if (cancelled) return;
            cfg = hydrateFromVersion(v);
          } catch {
            /* start from defaults if the current version can't be fetched */
          }
        }
        setConfig(cfg);
        setDirty(false);
        setSavedVersion(null);
        try {
          const list = await agentsApi.listVersions(routeId);
          if (!cancelled) setVersions(Array.isArray(list) ? list : []);
        } catch {
          if (!cancelled) setVersions([]);
        }
      } catch (e) {
        if (!cancelled) setLoadError(e.message || String(e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [routeId]);

  function patchConfig(patch) {
    setConfig((c) => ({ ...c, ...patch }));
    setDirty(true);
    setSavedVersion(null);
  }

  const err = useMemo(() => (key) => fieldErrors[key] || null, [fieldErrors]);

  async function refreshVersions() {
    try {
      const list = await agentsApi.listVersions(routeId);
      setVersions(Array.isArray(list) ? list : []);
    } catch {
      /* keep the stale list; the save banner still shows */
    }
  }

  async function saveAsNewVersion() {
    setSaving(true);
    setSaveError(null);
    setGeneralErrors([]);
    setFieldErrors({});
    try {
      const payload = buildVersionPayload(config);
      const localErrors = validateVersionPayload(payload, config);
      const keys = Object.keys(localErrors);
      if (keys.length) {
        setFieldErrors({ ...localErrors });
        setGeneralErrors(['Fix the highlighted problems before saving.']);
        const firstTab = keys.map(tabForErrorKey).find(Boolean);
        if (firstTab) setActiveTab(firstTab);
        setSaving(false);
        return;
      }
      const version = await agentsApi.createVersion(routeId, payload);
      setSavedVersion(version);
      setDirty(false);
      setAgent((a) => (a ? { ...a, current_version_id: version.id } : a));
      await refreshVersions();
      window.scrollTo({ top: 0, behavior: 'smooth' });
    } catch (e) {
      if (e && e.status === 422 && Array.isArray(e.body && e.body.detail)) {
        // Per-segment validation errors — surface them under their tabs.
        const fe = {};
        e.body.detail.forEach((d) => {
          const loc = Array.isArray(d.loc) ? d.loc.filter((p) => p !== 'body') : [];
          const seg = loc.length ? String(loc[0]) : '';
          const msg = d.msg || JSON.stringify(d);
          if (seg === 'question_flow') fe[seg + '.' + loc.slice(1).join('.')] = msg;
          else fe[seg] = msg;
        });
        setFieldErrors(fe);
        setGeneralErrors(['The server rejected some fields — fix them and save again.']);
        const firstTab = Object.keys(fe).map((k) => tabForErrorKey(k.split('.')[0])).find(Boolean);
        if (firstTab) setActiveTab(firstTab);
      } else {
        setSaveError(e.message || 'Could not save this version.');
      }
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <div className="loading-page">
        <span className="spinner" /> Loading agent…
      </div>
    );
  }

  if (loadError || !agent) {
    return (
      <div>
        <Link to="/agents" className="back-link">
          ← Agents
        </Link>
        <div className="banner banner-error">
          {loadError || 'Agent not found.'}{' '}
          <button type="button" className="btn btn-secondary btn-sm" onClick={() => window.location.reload()}>
            Retry
          </button>
        </div>
      </div>
    );
  }

  const latestVersionNumber = versions.length ? versions[versions.length - 1].version : null;

  return (
    <div>
      <Link to="/agents" className="back-link">
        ← Agents
      </Link>

      <div className="page-head detail-head">
        <div>
          <div className="title-row">
            <h2 className="page-title">{agent.name || 'Untitled agent'}</h2>
            <span className={`status-dot dot-${agent.status || 'draft'}`}>{agent.status || 'draft'}</span>
            {latestVersionNumber != null && (
              <span className="version-chip">current v{latestVersionNumber}</span>
            )}
          </div>
          {agent.description && <p className="page-sub">{agent.description}</p>}
        </div>
        <div className="head-actions">
          <button type="button" className="btn btn-secondary btn-sm" onClick={() => navigate(`/agents/${routeId}/edit`)}>
            Edit → creates v{(latestVersionNumber ?? 0) + 1}
          </button>
        </div>
      </div>

      {savedVersion && (
        <div className="banner banner-success">
          <strong>Version {savedVersion.version} saved.</strong> It is now the current version. Campaigns keep running their pinned version until you re-point them.
        </div>
      )}
      {saveError && <div className="banner banner-error">{saveError}</div>}
      {generalErrors.length > 0 && (
        <div className="banner banner-error">
          <ul className="error-list">
            {generalErrors.map((g, i) => (
              <li key={i}>{g}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="banner brand">
        Editing always creates a new version — history stays intact and old calls keep the version that made them.
      </div>

      <div className="detail">
        {/* ------------------------------ LEFT: tabbed config editor ------- */}
        <div className="card">
          <div className="tabs" role="tablist" aria-label="Agent configuration sections">
            {TABS.map((t) => (
              <button
                key={t.key}
                type="button"
                role="tab"
                aria-selected={activeTab === t.key}
                className={`tab${activeTab === t.key ? ' on' : ''}`}
                onClick={() => setActiveTab(t.key)}
              >
                {t.label}
              </button>
            ))}
          </div>

          <div className={`tabbody${activeTab === 'context' ? ' on' : ''}`}>
            <h3 className="card-title">Context</h3>
            <p className="hint">
              What the agent knows before it speaks: your organization's facts, behavior rules, the mandatory AI
              disclosure, and when to hand over to a human.
            </p>
            <ContextFieldsEditor
              value={config}
              onChange={patchConfig}
              errors={{
                company_context: err('company_context'),
                system_prompt: err('system_prompt'),
                disclosure_script: err('disclosure_script'),
                escalation_rules: err('escalation_rules'),
              }}
            />
          </div>

          <div className={`tabbody${activeTab === 'flow' ? ' on' : ''}`}>
            <h3 className="card-title">Question flow</h3>
            <p className="hint">
              The ordered script of questions asked on every call. Short, one-at-a-time questions work best over
              the phone.
            </p>
            <QuestionFlowEditor
              steps={config.questionFlow}
              onChange={(steps) => patchConfig({ questionFlow: steps })}
              error={err('question_flow')}
            />
            {Object.entries(fieldErrors)
              .filter(([k]) => k.startsWith('question_flow.') && k !== 'question_flow')
              .slice(0, 3)
              .map(([k, v]) => (
                <p key={k} className="hint hint-error">
                  {v}
                </p>
              ))}
          </div>

          <div className={`tabbody${activeTab === 'extraction' ? ' on' : ''}`}>
            <h3 className="card-title">Extraction schema</h3>
            <p className="hint">
              The structured output each call must produce — these become your spreadsheet columns at export time.
            </p>
            <ExtractionSchemaEditor
              rows={config.extractionRows}
              onChange={(rows) => patchConfig({ extractionRows: rows })}
              error={err('extraction_schema') || err('extraction_schema.duplicate')}
            />
            {Object.entries(fieldErrors)
              .filter(
                ([k]) =>
                  k.startsWith('extraction_schema.') &&
                  !['extraction_schema', 'extraction_schema.duplicate'].includes(k)
              )
              .slice(0, 5)
              .map(([k, v]) => (
                <p key={k} className="hint hint-error">
                  {v}
                </p>
              ))}
          </div>

          <div className={`tabbody${activeTab === 'voice' ? ' on' : ''}`}>
            <h3 className="card-title">Voice &amp; Model</h3>
            <p className="hint">How the agent sounds and which conversation model powers it.</p>
            <VoiceSettingsForm value={config.voice} onChange={(voice) => patchConfig({ voice })} error={err('voice_settings')} />
          </div>

          <div className="wizard-footer" style={{ borderTop: '1px solid var(--border)', marginTop: 8 }}>
            <span className="hint" style={{ margin: 0 }}>
              {dirty
                ? 'Changes apply to the next saved version only.'
                : savedVersion
                  ? ''
                  : `Editing from current v${latestVersionNumber ?? '—'} — saving snapshots a new immutable version.`}
            </span>
            <button type="button" className="btn btn-primary" disabled={saving} onClick={saveAsNewVersion}>
              {saving ? 'Saving version…' : 'Save as new version'}
            </button>
          </div>
        </div>

        {/* ------------------------------ RIGHT: version history ---------- */}
        <div className="card pad">
          <h3 style={{ fontFamily: 'var(--font-d)', fontSize: 15, marginBottom: 6 }}>Version history</h3>
          <p style={{ fontSize: 12.5, color: 'var(--dim)', marginBottom: 10 }}>
            Immutable snapshots — test any of them in the playground.
          </p>
          <div>
            {versions.length === 0 ? (
              <p className="hint">
                No saved versions yet — configure the tabs on the left and press <strong>Save as new version</strong>{' '}
                to make this agent testable.
              </p>
            ) : (
              versions
                .slice()
                .reverse()
                .map((v) => {
                  const isCurrent = agent.current_version_id === v.id;
                  const date = new Date(v.created_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
                  return (
                    <div key={v.id} className="ver">
                      <b>v{v.version}</b>
                      <span style={{ flex: 1, fontSize: 12.5, color: 'var(--dim)' }}>
                        {date}{isCurrent ? ' · current' : ''}
                      </span>
                      {isCurrent && <span className="cur-badge">current</span>}
                      <a className="btn sm ghost" href={`/playground/${v.id}`}>
                        Test this version
                      </a>
                    </div>
                  );
                })
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
