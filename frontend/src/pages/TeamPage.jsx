import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { getStoredUser, teamApi } from '../api.js';

/* Team — members, seats and invitations.
 *
 * Seats are a plan entitlement: members + live pending invites. The backend
 * refuses an invite past the limit with an upgrade-suggesting message; this
 * page surfaces that verbatim and links to billing. */

const ROLE_LABEL = { owner: 'Owner', admin: 'Admin', member: 'Member' };

function fmtDate(value) {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
}

function roleBadge(role) {
  const cls = role === 'owner' ? 'purple' : role === 'admin' ? 'cyan' : 'gray';
  return <span className={`badge ${cls}`}>{ROLE_LABEL[role] || role}</span>;
}

export default function TeamPage() {
  const me = getStoredUser();
  const canManage = Boolean(me && ['owner', 'admin'].includes(me.role));

  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [invite, setInvite] = useState({ email: '', role: 'member' });
  const [busy, setBusy] = useState(null);

  function load() {
    setLoading(true);
    setError(null);
    teamApi
      .list()
      .then(setData)
      .catch((e) => setError(e.message || String(e)))
      .finally(() => setLoading(false));
  }

  useEffect(load, []);

  function sendInvite(e) {
    e.preventDefault();
    setBusy('invite');
    setNotice(null);
    setError(null);
    teamApi
      .invite({ email: invite.email.trim(), role: invite.role })
      .then(() => {
        setNotice(`Invitation sent to ${invite.email.trim()}. The link is valid for 7 days.`);
        setInvite({ email: '', role: 'member' });
        load();
      })
      .catch((err) => setError(err.message || String(err)))
      .finally(() => setBusy(null));
  }

  function revoke(inv) {
    setBusy(`invite-${inv.id}`);
    setError(null);
    teamApi
      .revokeInvite(inv.id)
      .then(() => {
        setNotice(`Invitation for ${inv.email} revoked.`);
        load();
      })
      .catch((err) => setError(err.message || String(err)))
      .finally(() => setBusy(null));
  }

  function changeRole(member, role) {
    setBusy(`member-${member.id}`);
    setError(null);
    teamApi
      .setRole(member.id, role)
      .then(() => {
        setNotice(`${member.email} is now ${ROLE_LABEL[role] || role}.`);
        load();
      })
      .catch((err) => setError(err.message || String(err)))
      .finally(() => setBusy(null));
  }

  function remove(member) {
    if (!window.confirm(`Remove ${member.email} from the workspace? They lose access immediately.`)) {
      return;
    }
    setBusy(`member-${member.id}`);
    setError(null);
    teamApi
      .removeMember(member.id)
      .then(() => {
        setNotice(`${member.email} was removed.`);
        load();
      })
      .catch((err) => setError(err.message || String(err)))
      .finally(() => setBusy(null));
  }

  const members = data && Array.isArray(data.members) ? data.members : [];
  const invites = data && Array.isArray(data.invites) ? data.invites : [];
  const used = data ? Number(data.seats_used) : 0;
  const limit = data ? Number(data.seats_limit) : 0;
  const seatsFull = limit > 0 && used >= limit;
  const seatPct = limit > 0 ? Math.min(100, (used / limit) * 100) : 0;

  function canEditMember(member) {
    if (!canManage) return false;
    if (member.role === 'owner') return false;
    if (member.id === (me && me.id)) return false;
    if (me && me.role === 'admin' && member.role === 'admin') return false;
    return true;
  }

  return (
    <div>
      <div className="page-head">
        <div>
          <h2 className="page-title">Team</h2>
          <p className="page-sub">
            Invite teammates into this workspace. Seats are part of your plan.
          </p>
        </div>
        <div className="head-actions">
          <Link to="/credits" className="btn btn-secondary">
            Manage plan
          </Link>
        </div>
      </div>

      {error && (
        <div className="banner banner-error" style={{ marginBottom: 16 }}>
          {error}{' '}
          <Link to="/credits" className="btn btn-secondary btn-sm" style={{ marginLeft: 8 }}>
            View plans
          </Link>
        </div>
      )}

      {notice && (
        <div className="banner banner-success" style={{ marginBottom: 16 }}>
          {notice}
        </div>
      )}

      {loading && !data && (
        <div className="loading-page">
          <span className="spinner" /> Loading team…
        </div>
      )}

      {data && (
        <>
          <div className="card" style={{ marginBottom: 18 }}>
            <div className="seat-summary">
              <div>
                <div className="lbl">Seats used</div>
                <div className="seat-count">
                  <b>{used}</b> / {limit >= 999 ? 'custom' : limit}
                </div>
              </div>
              <div className="seat-bar">
                <div className="progress">
                  <b style={{ width: `${seatPct}%` }} />
                </div>
                <div className="seat-note">
                  Members plus pending invitations count against the seat limit.
                  {seatsFull
                    ? ' All seats are in use — remove someone or upgrade to invite more.'
                    : ` ${Math.max(0, limit - used)} seat${limit - used === 1 ? '' : 's'} free.`}
                </div>
              </div>
            </div>
          </div>

          <div className="grid g2" style={{ alignItems: 'start' }}>
            <div className="card">
              <div className="card-h">
                <h3>Members</h3>
                <span>{members.length} in this workspace</span>
              </div>
              <table className="tbl">
                <thead>
                  <tr>
                    <th>Email</th>
                    <th>Role</th>
                    <th>Joined</th>
                    {canManage && <th />}
                  </tr>
                </thead>
                <tbody>
                  {members.map((member) => {
                    const editable = canEditMember(member);
                    return (
                      <tr key={member.id}>
                        <td>
                          <span className="mono">{member.email}</span>
                          {me && member.id === me.id && (
                            <span className="badge gray" style={{ marginLeft: 8 }}>you</span>
                          )}
                        </td>
                        <td>
                          {editable ? (
                            <select
                              value={member.role}
                              disabled={busy === `member-${member.id}`}
                              onChange={(e) => changeRole(member, e.target.value)}
                              aria-label={`Role for ${member.email}`}
                              style={{ width: 110 }}
                            >
                              <option value="admin">Admin</option>
                              <option value="member">Member</option>
                            </select>
                          ) : (
                            roleBadge(member.role)
                          )}
                        </td>
                        <td className="mono">{fmtDate(member.created_at)}</td>
                        {canManage && (
                          <td style={{ textAlign: 'right' }}>
                            {editable && (
                              <button
                                type="button"
                                className="btn btn-ghost btn-sm"
                                disabled={busy === `member-${member.id}`}
                                onClick={() => remove(member)}
                              >
                                Remove
                              </button>
                            )}
                          </td>
                        )}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            <div>
              {canManage && (
                <div className="card">
                  <div className="card-h">
                    <h3>Invite a teammate</h3>
                    <span>7-day link</span>
                  </div>
                  <form className="invite-form" onSubmit={sendInvite}>
                    <div className="field">
                      <label htmlFor="invite-email">
                        Work email <span className="req-star">*</span>
                      </label>
                      <input
                        id="invite-email"
                        type="email"
                        value={invite.email}
                        placeholder="teammate@company.com"
                        onChange={(e) => setInvite({ ...invite, email: e.target.value })}
                      />
                    </div>
                    <div className="field">
                      <label htmlFor="invite-role">Role</label>
                      <select
                        id="invite-role"
                        value={invite.role}
                        onChange={(e) => setInvite({ ...invite, role: e.target.value })}
                      >
                        <option value="member">Member — agents, campaigns and calls</option>
                        <option value="admin">Admin — also billing and team</option>
                      </select>
                    </div>
                    <button
                      type="submit"
                      className="btn primary"
                      disabled={busy === 'invite' || !invite.email.trim() || seatsFull}
                    >
                      {busy === 'invite' ? 'Sending…' : 'Send invitation'}
                    </button>
                    <p className="hint">
                      They get an email with a one-time link and choose their own password.
                      Invitations expire after 7 days.
                    </p>
                  </form>
                </div>
              )}

              {canManage && (
                <div className="card" style={{ marginTop: 18 }}>
                  <div className="card-h">
                    <h3>Pending invitations</h3>
                    <span>{invites.length}</span>
                  </div>
                  <table className="tbl">
                    <thead>
                      <tr>
                        <th>Email</th>
                        <th>Role</th>
                        <th>Expires</th>
                        <th />
                      </tr>
                    </thead>
                    <tbody>
                      {invites.length === 0 && (
                        <tr>
                          <td colSpan={4} className="table-state">
                            No pending invitations.
                          </td>
                        </tr>
                      )}
                      {invites.map((inv) => (
                        <tr key={inv.id}>
                          <td className="mono">{inv.email}</td>
                          <td>{roleBadge(inv.role)}</td>
                          <td className="mono">{fmtDate(inv.expires_at)}</td>
                          <td style={{ textAlign: 'right' }}>
                            <button
                              type="button"
                              className="btn btn-ghost btn-sm"
                              disabled={busy === `invite-${inv.id}`}
                              onClick={() => revoke(inv)}
                            >
                              Revoke
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {!canManage && (
                <div className="card">
                  <div className="card-h">
                    <h3>Roles</h3>
                    <span>what each can do</span>
                  </div>
                  <ul className="credit-rules" style={{ padding: '6px 20px 18px' }}>
                    <li><b>Owner</b> — full control, including billing and removing admins.</li>
                    <li><b>Admin</b> — manages agents, campaigns, calls, billing and the team.</li>
                    <li><b>Member</b> — creates agents and runs campaigns; billing is read-only.</li>
                  </ul>
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
