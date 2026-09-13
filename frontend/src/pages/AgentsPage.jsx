import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { agentsApi } from '../api.js';

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
    <div>
      <div className="page-head">
        <div>
          <h2 className="page-title">Agents</h2>
          <p className="page-sub">
            Your AI callers. Each agent keeps its conversation flow, extraction fields and voice settings as numbered,
            immutable versions.
          </p>
        </div>
        <button type="button" className="btn primary" onClick={() => navigate('/agents/new')}>
          + New Agent
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
            No agents yet. Create your first agent to start building a call flow.
            <div className="form-actions">
              <button type="button" className="btn primary" onClick={() => navigate('/agents/new')}>
                + Create your first agent
              </button>
            </div>
          </div>
        </div>
      )}

      {hasAgents && (
        <div className="agent-grid">
          {agents.map((a) => {
            const info = versionInfo[a.id];
            return (
              <div key={a.id} className="card acard">
                <div className="top">
                  <span className={`sdot ${a.status || 'draft'}`}></span>
                  <h3>{a.name || 'Untitled agent'}</h3>
                  {info && <span className="vchip">v{info.version}</span>}
                </div>
                <p>{a.description || 'No description yet.'}</p>
                <div className="meta">
                  Updated {info && info.created_at ? fmtDate(info.created_at) : fmtDate(a.updated_at)} · {a.status || 'draft'}
                </div>
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
