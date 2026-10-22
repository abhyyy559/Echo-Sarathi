import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { agentsApi, api } from '../api.js';
import LeadCardForm, { ABSENT_STUDENT_DEFAULTS } from '../components/LeadCardForm.jsx';
import StatusBadge from '../components/StatusBadge.jsx';

export default function TestCallPage() {
  const [domains, setDomains] = useState([]);
  const [domainsError, setDomainsError] = useState(null);
  const [domainId, setDomainId] = useState('');
  const [agents, setAgents] = useState([]);
  const [agentId, setAgentId] = useState('');
  const [agentsError, setAgentsError] = useState(null);
  const [versions, setVersions] = useState([]);
  const [versionId, setVersionId] = useState('');
  const [contactCard, setContactCard] = useState({ ...ABSENT_STUDENT_DEFAULTS });
  const [to, setTo] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);
  const [placedWith, setPlacedWith] = useState(null);

  useEffect(() => {
    api.listDomainConfigs().then((list) => {
      setDomains(Array.isArray(list) ? list : []);
      setDomainsError(null);
    }).catch((e) => setDomainsError(e.message));
    agentsApi.list().then((list) => {
      const rows = Array.isArray(list) ? list : [];
      setAgents(rows);
      setAgentsError(null);
      // Make the page usable straight after login: preselect the newest agent
      // that actually has a saved version, so "Place test call" is enabled
      // without forcing the user through a selector they do not care about.
      if (rows.length) {
        const preferred =
          rows.find((a) => a.current_version_id != null) || rows[0];
        setAgentId(String(preferred.id));
      }
    }).catch((e) => {
      setAgents([]);
      setAgentsError(e.message || 'Could not load agents.');
    });
  }, []);

  useEffect(() => {
    if (!agentId) {
      setVersions([]);
      setVersionId('');
      return;
    }
    // Fall back to the agent's current_version_id immediately, so the call
    // button works even if the separate version-list request is slow.
    const selected = agents.find((a) => String(a.id) === String(agentId));
    if (selected && selected.current_version_id != null) {
      setVersionId(String(selected.current_version_id));
    }
    agentsApi.listVersions(agentId).then((list) => {
      const arr = Array.isArray(list) ? list : [];
      setVersions(arr);
      setVersionId(arr.length ? String(arr[arr.length - 1].id) : '');
    }).catch(() => {
      setVersions([]);
      setVersionId('');
    });
  }, [agentId]);

  async function placeCall() {
    setBusy(true);
    setError(null);
    setResult(null);
    const payload = {};
    if (domainId) payload.domain_config_id = Number(domainId);
    if (versionId) payload.agent_version_id = Number(versionId);
    const card = Object.fromEntries(
      Object.entries(contactCard || {}).filter(([, v]) => String(v || '').trim())
    );
    if (Object.keys(card).length) payload.contact = card;
    const trimmed = to.trim();
    if (trimmed) payload.to = trimmed;
    try {
      const res = await api.placeTestCall(payload);
      setResult(res || {});
      setPlacedWith(versionId ? `agent version ${versionId}` : 'latest agent version');
    } catch (e) {
      setError(e.message || 'Could not place test call.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="narrow">
      <div className="page-head">
        <div>
          <h2 className="page-title">Test call</h2>
          <p className="page-sub">
            Place a single call using a call domain config to verify the voice pipeline end-to-end.
          </p>
        </div>
      </div>

      <div className="card">
        <div className="field">
          <label htmlFor="tc-domain">Call domain (optional — derived from the agent version when blank)</label>
          <select id="tc-domain" value={domainId} onChange={(e) => setDomainId(e.target.value)}>
            <option value="">Select a call domain…</option>
            {domains.map((d) => (
              <option key={d.id} value={d.id}>
                {d.display_name || d.name}
                {d.version != null ? ` (v${d.version})` : ''}
              </option>
            ))}
          </select>
          {domainsError && <p className="hint hint-error">{domainsError}</p>}
          <p className="hint">
            Optional — leave blank to use the call domain attached to the selected agent version.
          </p>
        </div>

        <div className="field">
          <label htmlFor="tc-agent">Agent</label>
          <select id="tc-agent" value={agentId} onChange={(e) => setAgentId(e.target.value)}>
            <option value="">Select an agent…</option>
            {agents.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
          {agentsError && <p className="hint hint-error">{agentsError}</p>}
          {!agentsError && agents.length === 0 && (
            <p className="hint">
              No agents yet. <Link to="/agents/new">Create one in the builder</Link> and the latest
              saved version will be selected here automatically.
            </p>
          )}
        </div>

        <div className="field">
          <label htmlFor="tc-version">Agent version</label>
          <select
            id="tc-version"
            value={versionId}
            onChange={(e) => setVersionId(e.target.value)}
            disabled={!agentId}
          >
            <option value="">{agentId ? 'Latest version' : 'Pick an agent first…'}</option>
            {versions.map((v) => (
              <option key={v.id} value={v.id}>
                v{v.version} — saved {v.created_at ? new Date(v.created_at).toLocaleString() : `#${v.id}`}
              </option>
            ))}
          </select>
        </div>

        <details className="card" open>
          <summary>Who are we calling? (optional lead card)</summary>
          <LeadCardForm value={contactCard} onChange={setContactCard} defaults={ABSENT_STUDENT_DEFAULTS} />
        </details>

        <div className="field">
          <label htmlFor="tc-to">Call destination (optional)</label>
          <input
            id="tc-to"
            type="tel"
            value={to}
            placeholder="Uses the configured test number if left blank"
            onChange={(e) => setTo(e.target.value)}
          />
          <p className="hint">
            Any valid number works when the deployment allows it; leaving this blank dials the first configured sandbox number. Only call numbers you are authorized to call, and make sure the recipient has consented.
          </p>
        </div>

        {error && <div className="banner banner-error">{error}</div>}

        <div className="form-actions">
          <button className="btn btn-primary" disabled={busy || !(domainId || versionId)} onClick={placeCall}>
            {busy ? 'Placing call…' : 'Place test call'}
          </button>
        </div>

        {result && (
          <div className="banner banner-success">
            <strong>Test call placed.</strong>
            {placedWith && <span> Placed with {placedWith}.</span>}
            <div className="result-grid">
              <span>
                Status: <StatusBadge status={result.status} />
              </span>
              {result.call_id != null && (
                <span>
                  Call ID: <code>{String(result.call_id)}</code>
                </span>
              )}
              {result.provider_call_id && (
                <span>
                  Provider call ID: <code>{String(result.provider_call_id)}</code>
                </span>
              )}
            </div>
            {result.call_id != null && (
              <p className="result-link">
                <Link to={`/calls/${result.call_id}`}>View live call detail →</Link>
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
