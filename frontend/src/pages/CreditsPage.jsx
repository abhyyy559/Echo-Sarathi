import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { billingApi } from '../api.js';

const KIND_LABELS = {
  grant: { cls: 'ok', label: 'Welcome credit' },
  purchase: { cls: 'cyan', label: 'Top-up' },
  usage: { cls: 'warn', label: 'Call usage' },
};

function inr(value, digits = 2) {
  const n = Number(value);
  if (!Number.isFinite(n)) return '—';
  return n.toLocaleString('en-IN', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function fmtDateTime(value) {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  return d.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export default function CreditsPage() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [buying, setBuying] = useState(null);
  const [notice, setNotice] = useState(null);

  function load() {
    setLoading(true);
    setError(null);
    billingApi
      .summary()
      .then(setData)
      .catch((e) => setError(e.message || String(e)))
      .finally(() => setLoading(false));
  }

  useEffect(load, []);

  function buy(pack) {
    setBuying(pack.id);
    setNotice(null);
    billingApi
      .topup(pack.id)
      .then((next) => {
        setData(next);
        setNotice(`${pack.name} pack added — ${pack.minutes} minutes credited.`);
      })
      .catch((e) => setNotice(e.message || String(e)))
      .finally(() => setBuying(null));
  }

  const balance = data ? Number(data.balance_rupees) : 0;
  const minutes = data ? Number(data.minutes_remaining) : 0;
  const lowBalance = Boolean(data && data.low_balance);
  const paymentsOn = Boolean(data && data.manual_payments_enabled);
  const ledger = data && Array.isArray(data.ledger) ? data.ledger : [];
  const packs = data && Array.isArray(data.packs) ? data.packs : [];

  return (
    <div>
      <div className="page-head">
        <div>
          <h2 className="page-title">Credits</h2>
          <p className="page-sub">
            Prepaid wallet for live calls — metered to the second, no seats, no platform fee.
          </p>
        </div>
        <div className="head-actions">
          <Link to="/campaigns" className="btn primary">
            Run a campaign
          </Link>
        </div>
      </div>

      {error && (
        <div className="banner banner-error">
          {error}{' '}
          <button type="button" className="btn btn-secondary btn-sm" onClick={load}>
            Retry
          </button>
        </div>
      )}

      {loading && !data && (
        <div className="loading-page">
          <span className="spinner" /> Loading wallet…
        </div>
      )}

      {data && (
        <>
          {lowBalance && (
            <div className="banner banner-error" style={{ marginBottom: 16 }}>
              <strong>Your balance is running low.</strong> Campaigns stop dialing
              below ₹0.60 — top up to keep calls going.
            </div>
          )}

          {notice && (
            <div className="banner banner-success" style={{ marginBottom: 16 }}>
              {notice}
            </div>
          )}

          <div className="grid g5">
            <div className="card stat">
              <div className="lbl">Available credits</div>
              <div className="num">₹{inr(balance)}</div>
              <div className="foot">
                <span className={`badge ${lowBalance ? 'crit' : 'ok'}`}>
                  {lowBalance ? 'Top up soon' : 'Ready to dial'}
                </span>
              </div>
            </div>
            <div className="card stat">
              <div className="lbl">Minutes remaining</div>
              <div className="num">{inr(minutes, 1)}</div>
              <div className="foot">at ₹{inr(data.price_per_minute_rupees)} / min</div>
            </div>
            <div className="card stat">
              <div className="lbl">Spent this month</div>
              <div className="num">₹{inr(data.spent_this_month_rupees)}</div>
              <div className="foot">connected calls only</div>
            </div>
            <div className="card stat">
              <div className="lbl">Minutes this month</div>
              <div className="num">{inr(data.minutes_used_this_month, 1)}</div>
              <div className="foot">across all agents</div>
            </div>
            <div className="card stat">
              <div className="lbl">Rate</div>
              <div className="num">₹{inr(data.price_per_minute_rupees)}</div>
              <div className="foot">≈ 5 paise per second, billed per second</div>
            </div>
          </div>

          <div className="card" style={{ marginTop: 18 }}>
            <div className="card-h">
              <h3>Top up</h3>
              <span>credits never expire</span>
            </div>
            <div className="pack-grid">
              {packs.map((pack, i) => (
                <div key={pack.id} className={`pack${i === 1 ? ' featured' : ''}`}>
                  {i === 1 && <span className="pack-flag">Most popular</span>}
                  <div className="pack-name">{pack.name}</div>
                  <div className="pack-price">
                    ₹{inr(pack.price_paise / 100, 0)}
                    <small>one-time</small>
                  </div>
                  <div className="pack-minutes">
                    {Number(pack.minutes).toLocaleString('en-IN')} minutes · ₹
                    {inr(pack.per_minute_paise / 100)}/min
                  </div>
                  <p className="pack-blurb">{pack.blurb}</p>
                  <button
                    type="button"
                    className={`btn ${i === 1 ? 'primary' : 'btn-secondary'} btn-block`}
                    disabled={!paymentsOn || buying !== null}
                    onClick={() => buy(pack)}
                    title={paymentsOn ? '' : 'Online payments are not enabled yet'}
                  >
                    {buying === pack.id ? 'Adding…' : `Buy ${pack.name}`}
                  </button>
                </div>
              ))}
            </div>
            {!paymentsOn && (
              <div style={{ padding: '0 20px 18px', fontSize: 12.5, color: 'var(--dim)' }}>
                Online checkout is not enabled in this environment. To add credits,
                write to <a href="mailto:hello@echosarathi.ai">hello@echosarathi.ai</a> —
                packs are credited to your organization manually.
              </div>
            )}
          </div>

          <div className="grid g2" style={{ marginTop: 18 }}>
            <div className="card">
              <div className="card-h">
                <h3>How credits work</h3>
                <span>simple, prepaid</span>
              </div>
              <div style={{ padding: '6px 20px 18px' }}>
                <ul className="credit-rules">
                  <li>
                    <b>Only connected calls are billed.</b> Busy, no-answer and
                    failed legs cost you nothing.
                  </li>
                  <li>
                    <b>Metered to the second.</b> A 47-second call is 47 seconds
                    at ₹{inr(data.price_per_minute_rupees)}/min — rounded up to the
                    next second, never the next minute.
                  </li>
                  <li>
                    <b>Playground time is free.</b> Test any agent version in the
                    browser without spending a paisa.
                  </li>
                  <li>
                    <b>Campaigns pause themselves.</b> Below ₹0.60 of balance the
                    dialer stops placing legs; they resume as soon as you top up.
                  </li>
                  <li>
                    <b>Credits never expire</b> and carry across agents, campaigns
                    and team members.
                  </li>
                </ul>
              </div>
            </div>

            <div className="card">
              <div className="card-h">
                <h3>Wallet history</h3>
                <span>latest {ledger.length}</span>
              </div>
              <table className="tbl">
                <thead>
                  <tr>
                    <th>When</th>
                    <th>Activity</th>
                    <th>Amount</th>
                    <th>Balance</th>
                  </tr>
                </thead>
                <tbody>
                  {ledger.length === 0 && (
                    <tr>
                      <td colSpan={4} className="table-state">
                        No wallet activity yet — the welcome credit appears here.
                      </td>
                    </tr>
                  )}
                  {ledger.map((entry) => {
                    const kind = KIND_LABELS[entry.kind] || { cls: 'cyan', label: entry.kind };
                    const positive = entry.amount_paise >= 0;
                    return (
                      <tr key={entry.id}>
                        <td className="mono">{fmtDateTime(entry.created_at)}</td>
                        <td>
                          <span className={`badge ${kind.cls}`}>{kind.label}</span>{' '}
                          <span style={{ fontSize: 12.5 }}>{entry.description}</span>
                        </td>
                        <td
                          className="mono"
                          style={{ color: positive ? 'var(--green)' : 'var(--red)' }}
                        >
                          {positive ? '+' : '−'}₹{inr(Math.abs(entry.amount_rupees))}
                        </td>
                        <td className="mono">₹{inr(entry.balance_after_paise / 100)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
