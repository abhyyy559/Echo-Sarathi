import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api.js';
import usePoll from '../hooks/usePoll.js';
import { statusLabel, statusClass } from '../components/StatusBadge.jsx';
import Modal from '../components/Modal.jsx';

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
  });
}

export default function CampaignsPage() {
  const navigate = useNavigate();
  const { data: campaigns, error, loading, reload } = usePoll('/api/campaigns', 5000);

  const [showNew, setShowNew] = useState(false);
  const [domains, setDomains] = useState([]);
  const [domainsError, setDomainsError] = useState(null);
  const [agents, setAgents] = useState([]);
  const [agentsError, setAgentsError] = useState(null);
  const [form, setForm] = useState({ name: '', domain_config_id: '', agent_version_id: '' });
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState(null);

  useEffect(() => {
    api
      .listDomainConfigs()
      .then((list) => {
        setDomains(Array.isArray(list) ? list : []);
        setDomainsError(null);
      })
      .catch((e) => setDomainsError(e.message));
    api
      .listAgents()
      .then((list) => {
        setAgents(Array.isArray(list) ? list.filter((a) => a.current_version_id != null) : []);
        setAgentsError(null);
      })
      .catch((e) => setAgentsError(e.message));
  }, []);

  const hasAgentVersions = agents.length > 0;

  async function act(id, fn) {
    try {
      await fn(id);
    } catch (e) {
      setCreateError(e.message || 'Action failed.');
    } finally {
      reload();
    }
  }

  async function submitNew() {
    setCreating(true);
    setCreateError(null);
    try {
      const payload = { name: form.name.trim() };
      if (hasAgentVersions) {
        payload.agent_version_id = Number(form.agent_version_id);
      } else {
        payload.domain_config_id = form.domain_config_id;
      }
      const created = await api.createCampaign(payload);
      setShowNew(false);
      reload();
      if (created && created.id != null) {
        navigate(`/campaigns/${created.id}`);
      }
    } catch (e) {
      setCreateError(e.message || 'Could not create campaign.');
    } finally {
      setCreating(false);
    }
  }

  return (
    <div>
      <div className="page-head">
        <div>
          <h2 className="page-title">Campaigns</h2>
          <p className="page-sub">Upload contacts, pick an agent, launch. Calls run 9 AM – 9 PM IST.</p>
        </div>
        <button className="btn btn-primary" onClick={() => setShowNew(true)}>
          + New Campaign
        </button>
      </div>

      {error && (
        <div className="banner banner-error">
          {error}{' '}
          <button className="btn btn-secondary btn-sm" onClick={reload}>
            Retry
          </button>
        </div>
      )}

      {createError && (
        <div className="banner banner-error">{createError}</div>
      )}

      <div className="card" style={{ overflowX: 'auto' }}>
        <table className="tbl">
          <thead>
            <tr>
              <th>Campaign</th>
              <th>Agent</th>
              <th>Status</th>
              <th style={{ minWidth: 180 }}>Progress</th>
              <th>Created</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr>
                <td colSpan={6} className="text-muted" style={{ padding: 24, textAlign: 'center' }}>
                  Loading…
                </td>
              </tr>
            )}
            {!loading && (!campaigns || campaigns.length === 0) && (
              <tr>
                <td colSpan={6} style={{ padding: 24, textAlign: 'center' }}>
                  <span className="text-muted">No campaigns yet. </span>
                  <button className="btn btn-primary" onClick={() => setShowNew(true)}>
                    + Create your first campaign
                  </button>
                </td>
              </tr>
            )}
            {!loading &&
              (campaigns || []).map((c) => {
                const counts = c.counts || {};
                const done = counts.completed || 0;
                const total = counts.total || 0;
                const pct = total ? Math.round((done / total) * 100) : 0;

                return (
                  <tr
                    key={c.id}
                    onClick={() => navigate(`/campaigns/${c.id}`)}
                    style={{ cursor: 'pointer' }}
                  >
                    <td>
                      <b>{c.name || `Campaign ${c.id}`}</b>
                    </td>
                    <td style={{ color: 'var(--muted)' }}>{c.agent_name || c.domain_config_name || '—'}</td>
                    <td>
                      <span className={`chip ${statusClass(c.status)}`}>{statusLabel(c.status)}</span>
                    </td>
                    <td>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                        <div className="progress">
                          <b style={{ width: pct + '%' }}></b>
                        </div>
                        <span className="mono">
                          {done}/{total}
                        </span>
                      </div>
                    </td>
                    <td className="mono">{fmtDateTime(c.created_at)}</td>
                    <td onClick={(e) => e.stopPropagation()}>
                      {c.status === 'running' && (
                        <button className="btn sm ghost" onClick={() => act(c.id, api.pauseCampaign)}>Pause</button>
                      )}
                      {c.status === 'paused' && (
                        <button className="btn sm ghost" onClick={() => act(c.id, api.launchCampaign)}>Resume</button>
                      )}
                      {c.status !== 'completed' && c.status !== 'canceled' && c.status !== 'draft' && (
                        <button className="btn sm danger" style={{ marginLeft: 6 }} onClick={() => act(c.id, api.cancelCampaign)}>
                          Cancel
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
          </tbody>
        </table>
      </div>

      {showNew && (
        <Modal
          title="New campaign"
          onClose={() => setShowNew(false)}
          footer={
            <>
              <button className="btn btn-secondary" onClick={() => setShowNew(false)}>
                Cancel
              </button>
              <button
                className="btn btn-primary"
                disabled={
                  creating ||
                  !form.name.trim() ||
                  (hasAgentVersions ? !form.agent_version_id : !form.domain_config_id)
                }
                onClick={submitNew}
              >
                {creating ? 'Creating…' : 'Create campaign'}
              </button>
            </>
          }
        >
          <div className="field">
            <label htmlFor="camp-name">Campaign name</label>
            <input
              id="camp-name"
              type="text"
              autoFocus
              value={form.name}
              placeholder="e.g. Absent students follow-up — Aug 23"
              onChange={(e) => setForm({ ...form, name: e.target.value })}
            />
          </div>
          {hasAgentVersions ? (
            <div className="field">
              <label htmlFor="camp-agent">Agent (pinned version)</label>
              <select
                id="camp-agent"
                value={form.agent_version_id}
                onChange={(e) => setForm({ ...form, agent_version_id: e.target.value })}
              >
                <option value="">Select an agent…</option>
                {agents.map((a) => (
                  <option key={a.id} value={a.current_version_id}>
                    {a.name} — current version
                  </option>
                ))}
              </select>
              {agentsError && <p className="hint hint-error">{agentsError}</p>}
              <p className="hint">
                The campaign calls with the agent's current saved version. Editing the agent later never changes a
                running campaign until you point it at the new version.
              </p>
            </div>
          ) : (
            <div className="field">
              <label htmlFor="camp-domain">Call domain</label>
              <select
                id="camp-domain"
                value={form.domain_config_id}
                onChange={(e) => setForm({ ...form, domain_config_id: e.target.value })}
              >
                <option value="">Select a call domain…</option>
                {domains.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.display_name || d.name}
                    {d.version != null ? ` (v${d.version})` : ''}
                  </option>
                ))}
              </select>
              {(domainsError || agentsError) && (
                <p className="hint hint-error">{domainsError || agentsError}</p>
              )}
              {!domainsError && domains.length === 0 && (
                <p className="hint">
                  No call domains available yet — build an agent instead for full control of the conversation.
                </p>
              )}
            </div>
          )}
          {createError && <div className="banner banner-error">{createError}</div>}
          <p className="hint">
            After creating the campaign you will upload its contact list. Calls only run inside the 9 AM–9 PM IST
            calling window once launched.
          </p>
        </Modal>
      )}
    </div>
  );
}
