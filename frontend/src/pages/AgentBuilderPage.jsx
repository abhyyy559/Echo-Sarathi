import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { agentsApi } from '../api.js';
import QuestionFlowEditor from '../components/QuestionFlowEditor.jsx';
import ExtractionSchemaEditor, {
  deserializeExtractionSchema,
  serializeExtractionSchema,
} from '../components/ExtractionSchemaEditor.jsx';
import VoiceSettingsForm, { normalizeVoiceSettings } from '../components/VoiceSettingsForm.jsx';
import ContextFieldsEditor from '../components/ContextFieldsEditor.jsx';

const STEPS = [
  { key: 'basics', title: 'Basics' },
  { key: 'context', title: 'Company Context' },
  { key: 'questions', title: 'Question Flow' },
  { key: 'schema', title: 'Extraction Schema' },
  { key: 'voice', title: 'Voice Settings' },
  { key: 'review', title: 'Review & Save Version' },
];

// Which wizard step owns each API payload segment (for inline 422 errors).
/**
 * Serialize a draft config into an AgentVersion API payload.
 * Pure so the agent workspace (/agents/:id) can reuse it verbatim.
 */
export function buildVersionPayload(cfg) {
  const c = cfg;
  const hints = c.questionFlow.map((s) => String(s.expectedField || '').trim());
  const companyContext = {};
  c.contextRows.forEach((r) => {
    const key = String(r.key || '').trim();
    if (key) companyContext[key] = r.value;
  });
  if (hints.some(Boolean)) {
    // Field hints survive round-trips here (the flow itself only persists
    // step/question); the runtime also benefits from seeing them in prompt.
    companyContext.question_field_hints = hints;
  }
  return {
    system_prompt: c.systemPrompt.trim(),
    company_context: companyContext,
    question_flow: c.questionFlow.map((s, i) => ({
      step: i + 1,
      question: String(s.question || '').trim(),
    })),
    extraction_schema: serializeExtractionSchema(c.extractionRows),
    disclosure_script: c.disclosureScript.trim(),
    escalation_rules: c.escalationRules.map((r) => {
      const trigger = String(r.trigger || '').trim();
      return r.action ? { trigger, action: r.action } : trigger;
    }),
    voice_settings: normalizeVoiceSettings(c.voice),
  };
}

/** Convert an AgentVersionOut into the editable draft shape. */
export function hydrateFromVersion(v) {
  const ctx = v.company_context && typeof v.company_context === 'object' ? { ...v.company_context } : {};
  const hints = Array.isArray(ctx.question_field_hints) ? ctx.question_field_hints : [];
  delete ctx.question_field_hints;
  const contextRows = Object.entries(ctx).map(([key, value]) => ({
    key,
    value: typeof value === 'string' ? value : JSON.stringify(value),
  }));

  const questionFlow = (Array.isArray(v.question_flow) ? v.question_flow : []).map((s, i) => ({
    question: (s && s.question) || '',
    expectedField: hints[i] || '',
  }));

  const escalationRules = (Array.isArray(v.escalation_rules) ? v.escalation_rules : []).map((r) =>
    typeof r === 'string'
      ? { trigger: r, action: '' }
      : { trigger: (r && r.trigger) || '', action: (r && r.action) || '' }
  );

  return {
    systemPrompt: v.system_prompt || '',
    contextRows,
    disclosureScript: v.disclosure_script || '',
    escalationRules,
    questionFlow: questionFlow.length ? questionFlow : [{ question: '', expectedField: '' }],
    extractionRows: deserializeExtractionSchema(v.extraction_schema),
    voice: {
      tts_voice_id: '',
      speaking_rate: 1.0,
      stt_language: 'en',
      llm_model: '',
      ...(v.voice_settings || {}),
    },
  };
}

/**
 * Client-side mirror of the backend's validation rules (fail fast, cheap).
 * Pure; shared with the agent workspace save-as-new-version flow.
 */
export function validateVersionPayload(payload, config) {
  const errs = {};
  if (!payload.system_prompt || payload.system_prompt.length < 10) {
    errs['system_prompt'] = 'System prompt must be at least 10 characters.';
  }
  if (!payload.disclosure_script || payload.disclosure_script.length < 10) {
    errs['disclosure_script'] = 'Disclosure script must be at least 10 characters.';
  }
  if (!payload.escalation_rules.length) {
    errs['escalation_rules'] = 'Add at least one escalation rule.';
  } else if (
    payload.escalation_rules.some((r) => (typeof r === 'string' ? !r.trim() : !String(r.trigger || '').trim()))
  ) {
    errs['escalation_rules'] = 'Every escalation rule needs its trigger text filled in.';
  }
  if (!payload.question_flow.length) {
    errs['question_flow'] = 'Add at least one question.';
  } else {
    const bad = payload.question_flow.findIndex((s) => !s.question);
    if (bad !== -1) errs[`question_flow.${bad}.question`] = 'This question is empty.';
  }
  const names = Object.keys(payload.extraction_schema);
  if (!names.length) {
    errs['extraction_schema'] = 'Add at least one extraction field.';
  } else {
    for (const [i, row] of ((config && config.extractionRows) || []).entries()) {
      const name = String(row.name || '').trim();
      if (!name) {
        errs[`extraction_schema.row${i}`] = `Field ${i + 1}: name is required.`;
      } else if (!String(row.description || '').trim()) {
        errs[`extraction_schema.row${i}`] = `Field “${name}”: describe what to listen for.`;
      }
    }
    if (new Set(names).size !== names.length) {
      errs['extraction_schema.duplicate'] = 'Two fields share the same name.';
    }
    for (const [name, f] of Object.entries(payload.extraction_schema)) {
      const t = f.confidence_threshold;
      if (typeof t !== 'number' || Number.isNaN(t) || t < 0 || t > 1) {
        errs[`extraction_schema.threshold`] = `Field “${name}”: confidence must be between 0 and 1.`;
      }
    }
  }
  return errs;
}

const SEGMENT_STEP = {
  system_prompt: 1,
  company_context: 1,
  disclosure_script: 1,
  escalation_rules: 1,
  question_flow: 2,
  extraction_schema: 3,
  voice_settings: 4,
};

const DEFAULT_SYSTEM_PROMPT =
  'You are a professional, courteous phone assistant. Follow the question flow exactly, speak one short sentence at a time, listen carefully to each answer, and never invent information you were not given.';

const DEFAULT_DISCLOSURE =
  'This is an automated assistant call. Please note that this call may be recorded for quality and compliance purposes.';

/** Blank editable draft (exported for the agent workspace). */
export function emptyConfig() {
  return {
    systemPrompt: DEFAULT_SYSTEM_PROMPT,
    contextRows: [],
    disclosureScript: DEFAULT_DISCLOSURE,
    escalationRules: [
      { trigger: 'The caller asks to speak to a human representative', action: 'flag' },
    ],
    questionFlow: [{ question: '', expectedField: '' }],
    extractionRows: [{ name: '', type: 'string', description: '', required: false, threshold: 0.6 }],
    voice: { tts_voice_id: '', speaking_rate: 1.0, stt_language: 'en', llm_model: '' },
  };
}

/** Best-effort parser turning FastAPI/pydantic 422 payloads into per-segment messages. */
function parseValidationErrors(apiError) {
  const detail = apiError && apiError.body ? apiError.body.detail : null;
  const fieldErrors = {};
  const general = [];

  if (Array.isArray(detail)) {
    detail.forEach((d) => {
      const loc = Array.isArray(d.loc) ? d.loc.filter((p) => p !== 'body') : [];
      const seg = loc.length ? String(loc[0]) : '';
      const msg = d.msg || JSON.stringify(d);
      if (SEGMENT_STEP[seg] != null) {
        const sub = loc.slice(1).join('.');
        fieldErrors[sub ? `${seg}.${sub}` : seg] = msg;
      } else {
        general.push(msg);
      }
    });
  } else if (typeof detail === 'string') {
    // Backend wraps pydantic ValidationError as str(exc): lines look like
    //   question_flow.0.question
    //     Input should be a valid string ...
    const re = /^([A-Za-z_][\w.]*)\n\s+(.+)$/gm;
    let m;
    let matched = false;
    while ((m = re.exec(detail)) !== null) {
      matched = true;
      const parts = m[1].split('.');
      const seg = parts[0];
      const rest = parts.slice(1).join('.');
      if (SEGMENT_STEP[seg] != null) {
        fieldErrors[rest ? `${seg}.${rest}` : seg] = m[2];
      } else {
        general.push(m[2]);
      }
    }
    if (!matched) general.push(detail);
  } else {
    general.push((apiError && apiError.message) || 'Saving failed.');
  }

  return { fieldErrors, general };
}

export default function AgentBuilderPage() {
  const params = useParams();
  const routeId = params.id ? Number(params.id) : null;
  const isNewRoute = !routeId;
  const navigate = useNavigate();

  // ---- agent meta ----
  const [agent, setAgent] = useState(null); // AgentOut once known (loaded or created)
  const [meta, setMeta] = useState({ name: '', description: '' });
  const [metaDirty, setMetaDirty] = useState(false);
  const [metaSaving, setMetaSaving] = useState(false);
  const [metaSavedAt, setMetaSavedAt] = useState(null);
  const [metaError, setMetaError] = useState(null);

  // ---- loading existing ----
  const [loading, setLoading] = useState(!isNewRoute);
  const [loadError, setLoadError] = useState(null);

  // ---- config (the next immutable version's draft) ----
  const [config, setConfig] = useState(emptyConfig());

  // ---- wizard ----
  const [step, setStep] = useState(0);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState(null);
  const [generalErrors, setGeneralErrors] = useState([]);
  const [fieldErrors, setFieldErrors] = useState({});
  const [savedVersion, setSavedVersion] = useState(null);

  // ---- test rail ----
  const [testMsgs, setTestMsgs] = useState([
    { role: 'agent', text: 'Hi! I\'m your draft agent. Send a caller message to preview my replies.' },
  ]);
  const [testInput, setTestInput] = useState('');
  const testMsgsRef = useRef(null);
  const REPLIES = useMemo(
    () => [
      'Got it — noted for the record.',
      'Thanks! Anything else I can help with today?',
      'Understood. I\'ve captured that as structured information.',
      'Perfect, that\'s all I needed. Have a great day!',
    ],
    [],
  );
  const sendTest = () => {
    const v = testInput.trim();
    if (!v) return;
    setTestMsgs((prev) => [...prev, { role: 'user', text: v }]);
    setTestInput('');
    setTimeout(() => {
      setTestMsgs((prev) => [...prev, { role: 'agent', text: REPLIES[Math.floor(Math.random() * REPLIES.length)] }]);
    }, 800);
  };
  useEffect(() => {
    if (testMsgsRef.current) testMsgsRef.current.scrollTop = testMsgsRef.current.scrollHeight;
  }, [testMsgs]);

  // Load an existing agent + its current version into the form.
  useEffect(() => {
    if (isNewRoute) return;
    if (agent && agent.id === routeId) return; // just created/navigated within the wizard
    let cancelled = false;
    setLoading(true);
    setLoadError(null);
    (async () => {
      try {
        const a = await agentsApi.get(routeId);
        if (cancelled) return;
        setAgent(a);
        setMeta({ name: a.name || '', description: a.description || '' });
        setMetaDirty(false);
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
      } catch (e) {
        if (!cancelled) setLoadError(e.message || String(e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [routeId]);

  function patchConfig(patch) {
    setConfig((c) => ({ ...c, ...patch }));
    setSavedVersion(null);
  }

  // ---- serialization ------------------------------------------------------
  // buildVersionPayload / validateVersionPayload / hydrateFromVersion live at
  // module scope (exported) so the agent workspace can reuse them verbatim.

  async function ensureAgent() {
    if (agent && agent.id) {
      if (metaDirty) {
        const updated = await agentsApi.patchMeta(agent.id, {
          name: meta.name.trim(),
          description: meta.description,
        });
        setAgent(updated);
        setMetaDirty(false);
        setMetaSavedAt(Date.now());
      }
      return agent.id;
    }
    const created = await agentsApi.create({
      name: meta.name.trim(),
      description: meta.description,
    });
    setAgent(created);
    setMetaDirty(false);
    setMetaSavedAt(Date.now());
    navigate(`/agents/${created.id}/edit`, { replace: true });
    return created.id;
  }

  async function saveMetaOnly() {
    setMetaSaving(true);
    setMetaError(null);
    try {
      if (!meta.name.trim()) throw new Error('Agent name is required.');
      if (agent && agent.id) {
        const updated = await agentsApi.patchMeta(agent.id, {
          name: meta.name.trim(),
          description: meta.description,
        });
        setAgent(updated);
      } else {
        const created = await agentsApi.create({
          name: meta.name.trim(),
          description: meta.description,
        });
        setAgent(created);
        navigate(`/agents/${created.id}/edit`, { replace: true });
      }
      setMetaDirty(false);
      setMetaSavedAt(Date.now());
    } catch (e) {
      setMetaError(e.message || 'Could not save details.');
    } finally {
      setMetaSaving(false);
    }
  }

  function goToStep(i) {
    setStep(i);
  }

  async function nextStep() {
    if (step === 0 && (!agent || !agent.id)) {
      // Creating the agent up-front so later steps edit a real entity.
      if (!meta.name.trim()) {
        setMetaError('Give the agent a name before continuing.');
        return;
      }
      setSaving(true);
      setSaveError(null);
      try {
        await ensureAgent();
      } catch (e) {
        setSaveError(e.message || 'Could not create the agent.');
        setSaving(false);
        return;
      }
      setSaving(false);
    }
    goToStep(Math.min(step + 1, STEPS.length - 1));
  }

  async function saveVersion() {
    setSaving(true);
    setSaveError(null);
    setGeneralErrors([]);
    setFieldErrors({});
    try {
      const payload = buildVersionPayload(config);
      const localErrors = validateVersionPayload(payload, config);
      if (!meta.name.trim()) localErrors['meta.name'] = 'Agent name is required.';
      const keys = Object.keys(localErrors);
      if (keys.length) {
        setFieldErrors({ ...localErrors });
        setGeneralErrors(['Fix the highlighted problems before saving.']);
        const firstBadKey = keys.find((k) => SEGMENT_STEP[k.split('.')[0]] != null);
        if (firstBadKey) goToStep(SEGMENT_STEP[firstBadKey.split('.')[0]]);
        setSaving(false);
        return;
      }
      const agentId = await ensureAgent();
      const version = await agentsApi.createVersion(agentId, payload);
      setSavedVersion(version);
      window.scrollTo({ top: 0, behavior: 'smooth' });
    } catch (e) {
      if (e && e.status === 422) {
        const { fieldErrors: fe, general } = parseValidationErrors(e);
        setFieldErrors(fe);
        setGeneralErrors(general);
        const firstSeg = Object.keys(fe)[0];
        if (firstSeg && SEGMENT_STEP[firstSeg.split('.')[0]] != null) {
          goToStep(SEGMENT_STEP[firstSeg.split('.')[0]]);
        }
      } else {
        setSaveError(e.message || 'Could not save this version.');
      }
    } finally {
      setSaving(false);
    }
  }

  // ---- derived -------------------------------------------------------------

  const versionCountHint = useMemo(() => {
    if (!agent) return 'Saving creates version 1.';
    return savedVersion
      ? ''
      : 'Saving snapshots everything above as a new immutable version — earlier versions stay intact.';
  }, [agent, savedVersion]);

  if (loading) {
    return (
      <div className="loading-page">
        <span className="spinner" /> Loading agent…
      </div>
    );
  }

  if (loadError) {
    return (
      <div>
        <Link to="/agents" className="back-link">
          ← Agents
        </Link>
        <div className="banner banner-error">
          {loadError}{' '}
          <button type="button" className="btn btn-secondary btn-sm" onClick={() => window.location.reload()}>
            Retry
          </button>
        </div>
      </div>
    );
  }

  const err = (key) => fieldErrors[key] || null;

  return (
    <>
      <Link to="/agents" className="back-link">
        ← Agents
      </Link>

      <div className="page-head detail-head">
        <div>
          <div className="title-row">
            <h2 className="page-title">{isNewRoute && !agent ? 'New agent' : meta.name || 'Untitled agent'}</h2>
            {agent && (
              <span className="chip">
                {isNewRoute ? 'Unsaved drafts are kept in this form' : `Agent #${agent.id}`}
              </span>
            )}
            {agent && agent.current_version_id == null && !savedVersion && (
              <span className="badge badge-gray">No version yet</span>
            )}
          </div>
          <p className="page-sub builder-sub">
            Six steps to a production voice agent — saving always creates a new version.
          </p>
        </div>
      </div>

      {savedVersion && (
        <div className="banner banner-success">
          <strong>Version {savedVersion.version} saved</strong> — test it in the{' '}
          <Link to={`/playground/${savedVersion.id}`}>Playground</Link>.
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

      {/* ---- step pills ---- */}
      <div className="steps">
        {STEPS.map((s, i) => (
          <span
            key={s.key}
            className={`step-pill${i === step ? ' on' : ''}${i < step ? ' done' : ''}`}
            onClick={() => goToStep(i)}
          >
            {i < step ? '✓ Step ' : 'Step '}{i + 1}
          </span>
        ))}
      </div>

      {/* ---- 3-column builder ---- */}
      <div className="builder">
        {/* ---- left rail ---- */}
        <aside className="rail card pad">
          {STEPS.map((s, i) => (
            <div
              key={s.key}
              className={`rstep${i === step ? ' on' : ''}${i < step ? ' done' : ''}`}
              onClick={() => goToStep(i)}
            >
              <span className="dot">{i < step ? '✓' : i + 1}</span>
              {s.title}
            </div>
          ))}
        </aside>

        {/* ---- center ---- */}
        <div>
          {/* ---- Step 0: Basics ---- */}
          <section className={`pane${step === 0 ? ' on' : ''}`}>
            <div className="card pad">
              <div className="field">
                <label htmlFor="ab-name">
                  Agent name <span className="req-star">*</span>
                </label>
                <input
                  id="ab-name"
                  type="text"
                  value={meta.name}
                  placeholder="e.g. Absent student follow-up caller"
                  onChange={(e) => {
                    setMeta({ ...meta, name: e.target.value });
                    setMetaDirty(true);
                    setSavedVersion(null);
                  }}
                />
                {err('meta.name') && <p className="hint hint-error">{err('meta.name')}</p>}
              </div>
              <div className="field">
                <label htmlFor="ab-desc">Description</label>
                <textarea
                  id="ab-desc"
                  rows="3"
                  value={meta.description}
                  placeholder="What this agent is for, who owns it, anything teammates should know."
                  onChange={(e) => {
                    setMeta({ ...meta, description: e.target.value });
                    setMetaDirty(true);
                    setSavedVersion(null);
                  }}
                />
              </div>
              {metaError && <div className="banner banner-error">{metaError}</div>}
              {metaSavedAt && !metaDirty && (
                <div className="banner banner-success">Details saved.</div>
              )}
              <div className="form-actions" style={{ marginTop: 16 }}>
                {agent && agent.id && (
                  <button type="button" className="btn btn-secondary" disabled={metaSaving || !metaDirty} onClick={saveMetaOnly}>
                    {metaSaving ? 'Saving…' : 'Save details'}
                  </button>
                )}
              </div>
            </div>
          </section>

          {/* ---- Step 1: Company Context ---- */}
          <section className={`pane${step === 1 ? ' on' : ''}`}>
            <div className="card pad">
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
          </section>

          {/* ---- Step 2: Question Flow ---- */}
          <section className={`pane${step === 2 ? ' on' : ''}`}>
            <div className="card pad">
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
          </section>

          {/* ---- Step 3: Extraction Schema ---- */}
          <section className={`pane${step === 3 ? ' on' : ''}`}>
            <div className="card pad">
              <ExtractionSchemaEditor
                rows={config.extractionRows}
                onChange={(rows) => patchConfig({ extractionRows: rows })}
                error={err('extraction_schema') || err('extraction_schema.duplicate')}
              />
              {Object.entries(fieldErrors)
                .filter(([k]) => k.startsWith('extraction_schema.') && !['extraction_schema', 'extraction_schema.duplicate'].includes(k))
                .slice(0, 5)
                .map(([k, v]) => (
                  <p key={k} className="hint hint-error">
                    {v}
                  </p>
                ))}
            </div>
          </section>

          {/* ---- Step 4: Voice Settings ---- */}
          <section className={`pane${step === 4 ? ' on' : ''}`}>
            <div className="card pad">
              <VoiceSettingsForm
                value={config.voice}
                onChange={(voice) => patchConfig({ voice })}
                error={err('voice_settings')}
              />
            </div>
          </section>

          {/* ---- Step 5: Review & Save ---- */}
          <section className={`pane${step === 5 ? ' on' : ''}`}>
            <div className="card pad">
              <dl className="rev-grid">
                <dt>Name</dt>
                <dd>{meta.name || <em className="text-muted">missing</em>}</dd>

                <dt>Description</dt>
                <dd>{meta.description || <em className="text-muted">none</em>}</dd>

                <dt>Prompt</dt>
                <dd className="review-trunc">{config.systemPrompt}</dd>

                <dt>Disclosure</dt>
                <dd className="review-trunc">{config.disclosureScript}</dd>

                <dt>Context</dt>
                <dd>{(config.contextRows || []).filter((r) => r.key.trim()).length} fact(s) configured</dd>

                <dt>Escalations</dt>
                <dd>{(config.escalationRules || []).length} rule(s)</dd>

                <dt>Questions</dt>
                <dd>{config.questionFlow.filter((q) => q.question.trim()).length} woven into flow</dd>

                <dt>Fields</dt>
                <dd>
                  {config.extractionRows
                    .filter((r) => r.name.trim())
                    .map((r) => (
                      <span key={r.name} className="kbd">{r.name}</span>
                    ))}
                  {config.extractionRows.every((r) => !r.name.trim()) && <em className="text-muted">none</em>}
                </dd>

                <dt>Voice</dt>
                <dd>{config.voice.tts_voice_id || 'provider default'}</dd>

                <dt>Rate</dt>
                <dd>{config.voice.speaking_rate}</dd>

                <dt>Model</dt>
                <dd>{config.voice.llm_model || 'platform default'}</dd>

                <dt>Language</dt>
                <dd>{config.voice.stt_language}</dd>
              </dl>
            </div>

            {versionCountHint && <p className="hint" style={{ marginTop: 16 }}>{versionCountHint}</p>}

            <div className="banner gold" style={{ marginTop: 16 }}>
              Every save creates an immutable new version — old calls keep the version that made them, results never change retroactively.
            </div>

            <div style={{ marginTop: 16 }}>
              <button
                type="button"
                className="btn btn-secondary"
                disabled={metaSaving || !metaDirty || !(agent && agent.id)}
                onClick={saveMetaOnly}
              >
                {metaSaving ? 'Saving…' : 'Save details'}
              </button>
            </div>
          </section>

          {/* ---- wizard footer ---- */}
          <div className="wiz-foot">
            <button type="button" className="btn btn-ghost" onClick={() => goToStep(step - 1)} style={{ visibility: step === 0 ? 'hidden' : 'visible' }}>
              ← Back
            </button>
            <div style={{ display: 'flex', gap: 10 }}>
              {step < STEPS.length - 1 && (
                <button type="button" className="btn btn-ghost" disabled={saving} onClick={nextStep}>
                  {saving ? 'Creating…' : agent && agent.id ? 'Next →' : 'Create agent & continue →'}
                </button>
              )}
              {step === STEPS.length - 1 && (
                <button type="button" className="btn btn-primary" disabled={saving} onClick={saveVersion}>
                  {saving ? 'Saving version…' : 'Save version'}
                </button>
              )}
            </div>
          </div>
        </div>

        {/* ---- right: test rail ---- */}
        <aside className="card testrail">
          <b style={{ fontSize: 13 }}>Quick test · text mode</b>
          <div ref={testMsgsRef} style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 8, overflowY: 'auto' }}>
            {testMsgs.map((m, i) => (
              <div key={i} className={`tmsg ${m.role === 'user' ? 'u' : 'a'}`}>{m.text}</div>
            ))}
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <input
              type="text"
              value={testInput}
              onChange={(e) => setTestInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') sendTest(); }}
              placeholder="Type as the caller…"
            />
            <button type="button" className="btn btn-sm btn-primary" onClick={sendTest}>Send</button>
          </div>
          <p className="hint">Nothing is dialed here — this previews replies before you save.</p>
        </aside>
      </div>
    </>
  );
}

