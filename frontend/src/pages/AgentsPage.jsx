import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { agentsApi } from '../api.js';
import '../workspace-pages.css';

function fmtDate(value) {
  if (!value) return '';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return '';
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

/**
 * Agents — Vapi/Retell-style card grid. Each card: status dot, name,
 * current-version chip, description and Test / Configure actions.
 */
export default function AgentsPage() {
  const navigate = useNavigate();
  const [agents, setAgents] = useState(null);
  const [versionInfo, setVersionInfo] = useState({}); // agent_id -> {version, created_at}
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    agentsApi
      .list()
      .then(async (list) => {
        if (cancelled) return;
        const rows = Array.isArray(list) ? list : [];
        setAgents(rows);
        // AgentOut carries current_version_id but not the human version number,
        // so hydrate "vN" from each agent's immutable version history.
        await Promise.all(
          rows
            .filter((a) => a.current_version_id != null)
            .map(async (a) => {
              try {
                const versions = await agentsApi.listVersions(a.id);
                if (cancelled || !Array.isArray(versions) || versions.length === 0) return;
                const latest = versions[versions.length - 1];
                setVersionInfo((prev) => ({
                  ...prev,
                  [a.id]: { version: latest.version, created_at: latest.created_at },
                }));
              } catch {
                /* leave the card without a chip; it still renders */
              }
            })
        );
      })
      .catch((e) => {
        if (!cancelled) setError(e.message || String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [nonce]);

  const hasAgents = !loading && agents && agents.length > 0;

  return (
    <div className="es-workspace es-workspace-agents">
      <div className="page-head">
        <div>
          <h2 className="page-title">Agents</h2>
          <p className="page-sub">Configure who calls, what they ask and which fields they capture. Test a saved version before using it in a campaign.</p>
        </div>
        <button type="button" className="btn primary" onClick={() => navigate('/agents/new')}>
          New agent
        </button>
      </div>

      {error && (
        <div className="banner banner-error">
          {error}{' '}
          <button type="button" className="btn ghost" onClick={() => setNonce((n) => n + 1)}>
            Retry
          </button>
        </div>
      )}

      {loading && (
        <div className="loading-page">
          <span className="spinner" /> Loading agents…
        </div>
      )}

      {!loading && agents && agents.length === 0 && (
        <div className="card">
          <div className="empty-state">
            <h3>Create your first caller</h3>
            <p>Start with an identity, add your question flow and choose the information each call should capture.</p>
            <div className="form-actions">
              <button type="button" className="btn primary" onClick={() => navigate('/agents/new')}>
                Create your first agent
              </button>
            </div>
          </div>
        </div>
      )}

      {hasAgents && (
        <div className="agent-grid">
          {agents.map((a) => {
            const info = versionInfo[a.id];
            const initials = (a.name || '?')
              .split(/\s+/)
              .filter(Boolean)
              .slice(0, 2)
              .map((part) => part[0].toUpperCase())
              .join('');
            return (
              <div key={a.id} className="card acard" role="group" aria-label={a.name || 'Untitled agent'}>
                <div className="top">
                  <span className={`avatar ${a.status || 'draft'}`} aria-hidden="true">{initials || '?'}</span>
                  <div className="who">
                    <h3>{a.name || 'Untitled agent'}</h3>
                    <span className="es-workspace-cell-note">Agent #{a.id}</span>
                  </div>
                  {info && <span className="vchip">Version {info.version}</span>}
                </div>
                <p className="es-workspace-agent-role">{a.description || 'No role set yet. Add one in the builder.'}</p>
                <div className="meta">
                  <span><span className={`sdot ${a.status || 'draft'}`} aria-hidden="true"></span>{a.status || 'draft'}</span>
                  <span>Updated {info && info.created_at ? fmtDate(info.created_at) : fmtDate(a.updated_at)}</span>
                </div>
                {a.current_version_id == null && <p className="hint">Save a version to enable testing.</p>}
                <div className="acts">
                  <button
                    type="button"
                    className="btn sm primary"
                    disabled={a.current_version_id == null}
                    title={
                      a.current_version_id == null
                        ? 'Save at least one version from the builder to test'
                        : 'Talk or type with this agent in the Playground'
                    }
                    onClick={() => navigate(`/playground/${a.current_version_id}`)}
                  >
                    Test
                  </button>
                  <button type="button" className="btn sm ghost" onClick={() => navigate(`/agents/${a.id}`)}>
                    Configure
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {hasAgents && (
        <p className="hint" style={{ marginTop: 16 }}>
          Tip: an agent becomes callable once you save at least one version — every save snapshots a new immutable
          version.
        </p>
      )}
    </div>
  );
}
