import React, { useEffect, useState } from 'react';
import { billingApi, platformApi } from '../api.js';

/* Platform admin — the operator console for the sales-led motion.
 * Visible only to emails in PLATFORM_ADMIN_EMAILS; the backend enforces it,
 * this page just refuses to look like a dead end for everyone else. */

function inr(value, digits = 0) {
  const n = Number(value);
  if (!Number.isFinite(n)) return '—';
  return n.toLocaleString('en-IN', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function fmtDate(value) {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
}

const EMPTY_CREDIT = { amount: '', description: '' };
const EMPTY_PLAN = { plan_id: 'starter', months: '1', included_minutes: '', price: '' };

export default function AdminPage() {
  const [summary, setSummary] = useState(null);
  const [orgs, setOrgs] = useState([]);
  const [plans, setPlans] = useState([]);
  const [query, setQuery] = useState('');
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [forbidden, setForbidden] = useState(false);
  const [notice, setNotice] = useState(null);
  const [busy, setBusy] = useState(null);
  const [credit, setCredit] = useState(EMPTY_CREDIT);
  const [planForm, setPlanForm] = useState(EMPTY_PLAN);

  function load(queryValue) {
    setLoading(true);
    setError(null);
    Promise.all([
      platformApi.summary(),
      platformApi.orgs(typeof queryValue === 'string' ? queryValue : query),
      billingApi.plans().catch(() => ({ plans: [] })),
    ])
      .then(([summaryData, orgData, planData]) => {
        setSummary(summaryData);
        setOrgs(Array.isArray(orgData.orgs) ? orgData.orgs : []);
        setPlans(Array.isArray(planData.plans) ? planData.plans : []);
        setForbidden(false);
      })
      .catch((e) => {
        if (e.status === 403) setForbidden(true);
        else setError(e.message || String(e));
      })
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    load('');
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function search(e) {
    e.preventDefault();
    load(query.trim());
  }

  function openOrg(org) {
    setBusy(`org-${org.id}`);
    setNotice(null);
    setError(null);
    platformApi
      .org(org.id)
      .then((data) => {
        setDetail(data);
        setPlanForm({ ...EMPTY_PLAN, plan_id: data.plan_id || 'starter' });
        setCredit(EMPTY_CREDIT);
      })
      .catch((err) => setError(err.message || String(err)))
      .finally(() => setBusy(null));
  }

  function refreshDetail(orgId) {
    platformApi
      .org(orgId)
      .then(setDetail)
      .catch(() => {});
    load(query.trim());
  }

  function adjustCredits(e) {
    e.preventDefault();
    if (!detail) return;
    const amountPaise = Math.round(Number(credit.amount) * 100);
    if (!Number.isFinite(amountPaise) || amountPaise === 0) {
      setError('Enter a non-zero amount (negative to deduct).');
      return;
    }
    setBusy('credit');
    setError(null);
    platformApi
      .adjustCredits(detail.id, {
        amountPaise,
        description: credit.description.trim() || 'Manual adjustment',
      })
      .then((res) => {
        setNotice(
          `${amountPaise > 0 ? 'Credited' : 'Deducted'} ₹${inr(
            Math.abs(amountPaise) / 100,
            2
          )} — balance is now ₹${inr(res.balance_after_paise / 100, 2)}.`
        );
        setCredit(EMPTY_CREDIT);
        refreshDetail(detail.id);
      })
      .catch((err) => setError(err.message || String(err)))
      .finally(() => setBusy(null));
  }

  function assignPlan(e) {
    e.preventDefault();
    if (!detail) return;
    const body = {
      plan_id: planForm.plan_id,
      months: Math.max(1, Number(planForm.months) || 1),
    };
    if (planForm.included_minutes !== '') {
      body.included_minutes = Math.max(0, Math.round(Number(planForm.included_minutes) || 0));
    }
    if (planForm.price !== '') {
      body.price_paise = Math.max(0, Math.round(Number(planForm.price) * 100));
    }
    setBusy('plan');
    setError(null);
    platformApi
      .assignPlan(detail.id, body)
      .then((res) => {
        setNotice(
          res.plan_id === 'free'
            ? 'Plan cleared — the organization is back on Free.'
            : `${res.plan_id} plan assigned until ${fmtDate(res.subscription?.period_end)}.`
        );
        refreshDetail(detail.id);
      })
      .catch((err) => setError(err.message || String(err)))
      .finally(() => setBusy(null));
  }

  function runLifecycle() {
    if (!window.confirm('Expire lapsed plan periods and send renewal reminders now?')) return;
    setBusy('lifecycle');
    setError(null);
    platformApi
      .runLifecycle()
      .then((counts) => {
        setNotice(
          `Lifecycle run: ${counts.expired || 0} expired, ${counts.reminded || 0} reminder(s) sent.`
        );
        load(query.trim());
      })
      .catch((err) => setError(err.message || String(err)))
      .finally(() => setBusy(null));
  }

  if (forbidden) {
    return (
      <div className="empty-state">
        Platform administration is restricted to operator accounts.
      </div>
    );
  }

  return (
    <div>
      <div className="page-head">
        <div>
          <h2 className="page-title">Platform admin</h2>
          <p className="page-sub">
            Every organization, contract pricing, credit adjustments and billing lifecycle.
          </p>
        </div>
        <div className="head-actions">
          <button
            type="button"
            className="btn btn-secondary"
            disabled={busy === 'lifecycle'}
            onClick={runLifecycle}
          >
            {busy === 'lifecycle' ? 'Running…' : 'Run billing lifecycle'}
          </button>
        </div>
      </div>

      {error && (
        <div className="banner banner-error" style={{ marginBottom: 16 }}>
          {error}
        </div>
      )}
      {notice && (
        <div className="banner banner-success" style={{ marginBottom: 16 }}>
          {notice}
        </div>
      )}

      {loading && !summary && (
        <div className="loading-page">
          <span className="spinner" /> Loading platform data…
        </div>
      )}

      {summary && (
        <div className="grid g5">
          <div className="card stat">
            <div className="lbl">Organizations</div>
            <div className="num">{inr(summary.organizations)}</div>
            <div className="foot">all tenants</div>
          </div>
          <div className="card stat">
            <div className="lbl">Active plans</div>
            <div className="num">{inr(summary.active_plans)}</div>
            <div className="foot">paid periods running</div>
          </div>
          <div className="card stat">
            <div className="lbl">Active plan value</div>
            <div className="num">₹{inr(summary.active_plan_value_paise / 100)}</div>
            <div className="foot">per period, incl. GST</div>
          </div>
          <div className="card stat">
            <div className="lbl">Wallet float</div>
            <div className="num">₹{inr(summary.wallet_float_paise / 100)}</div>
            <div className="foot">unconsumed prepaid credit</div>
          </div>
          <div className="card stat">
            <div className="lbl">Minutes this month</div>
            <div className="num">{inr(summary.minutes_this_month, 1)}</div>
            <div className="foot">connected, platform-wide</div>
          </div>
        </div>
      )}

      <div className="card" style={{ marginTop: 18 }}>
        <div className="card-h">
          <h3>Organizations</h3>
          <form className="admin-search" onSubmit={search}>
            <input
              type="search"
              value={query}
              placeholder="Search name or slug…"
              onChange={(e) => setQuery(e.target.value)}
            />
            <button type="submit" className="btn btn-secondary btn-sm">
              Search
            </button>
          </form>
        </div>
        <table className="tbl">
          <thead>
            <tr>
              <th>Organization</th>
              <th>Plan</th>
              <th>Period ends</th>
              <th>Wallet</th>
              <th>Users</th>
              <th>Agents</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {orgs.length === 0 && !loading && (
              <tr>
                <td colSpan={7} className="table-state">
                  No organizations match.
                </td>
              </tr>
            )}
            {orgs.map((org) => (
              <tr key={org.id} className={detail && detail.id === org.id ? 'row-active' : ''}>
                <td>
                  <div style={{ fontWeight: 600 }}>{org.name}</div>
                  <div className="mono" style={{ fontSize: 11.5, color: 'var(--dim)' }}>
                    {org.slug} · #{org.id}
                  </div>
                </td>
                <td>
                  <span className="badge cyan">{org.plan_id}</span>
                  {org.cancel_at_period_end && (
                    <span className="badge warn" style={{ marginLeft: 6 }}>ending</span>
                  )}
                </td>
                <td className="mono">{fmtDate(org.period_end)}</td>
                <td className="mono">₹{inr(org.balance_paise / 100)}</td>
                <td className="mono">{org.users}</td>
                <td className="mono">{org.agents}</td>
                <td style={{ textAlign: 'right' }}>
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    disabled={busy === `org-${org.id}`}
                    onClick={() => openOrg(org)}
                  >
                    Manage
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {detail && (
        <>
          <div className="card" style={{ marginTop: 18 }}>
            <div className="card-h">
              <h3>{detail.name}</h3>
              <span>
                {detail.slug} · {detail.billing?.plan?.name || detail.plan_id} ·{' '}
                ₹{inr((detail.billing?.balance_paise || 0) / 100, 2)} wallet
              </span>
            </div>
            <div className="admin-detail">
              <div>
                <div className="lbl">Current period</div>
                <div className="admin-detail-value">
                  {detail.billing?.subscription
                    ? `${fmtDate(detail.billing.subscription.period_start)} → ${fmtDate(
                        detail.billing.subscription.period_end
                      )}`
                    : 'No paid period — Free plan'}
                </div>
              </div>
              <div>
                <div className="lbl">Included minutes</div>
                <div className="admin-detail-value">
                  {detail.billing?.subscription
                    ? `${inr(detail.billing.included_minutes_used, 1)} / ${inr(
                        detail.billing.included_minutes_total
                      )} used`
                    : '—'}
                </div>
              </div>
              <div>
                <div className="lbl">Users / agents</div>
                <div className="admin-detail-value">
                  {detail.users} / {detail.agents}
                </div>
              </div>
            </div>
          </div>

          <div className="grid g2" style={{ marginTop: 18, alignItems: 'start' }}>
            <div className="card">
              <div className="card-h">
                <h3>Adjust wallet</h3>
                <span>signed amount, audited</span>
              </div>
              <form className="billing-form" onSubmit={adjustCredits}>
                <div className="field">
                  <label htmlFor="adjust-amount">Amount in rupees</label>
                  <input
                    id="adjust-amount"
                    type="number"
                    step="0.01"
                    value={credit.amount}
                    placeholder="e.g. 2990 or -500"
                    onChange={(e) => setCredit({ ...credit, amount: e.target.value })}
                  />
                  <p className="hint">Positive credits the wallet; negative deducts.</p>
                </div>
                <div className="field">
                  <label htmlFor="adjust-note">Description</label>
                  <input
                    id="adjust-note"
                    type="text"
                    value={credit.description}
                    placeholder="Offline payment, refund, goodwill…"
                    onChange={(e) => setCredit({ ...credit, description: e.target.value })}
                  />
                </div>
                <button type="submit" className="btn primary" disabled={busy === 'credit'}>
                  {busy === 'credit' ? 'Applying…' : 'Apply adjustment'}
                </button>
              </form>
            </div>

            <div className="card">
              <div className="card-h">
                <h3>Assign a plan</h3>
                <span>contracts, comps, upgrades</span>
              </div>
              <form className="billing-form" onSubmit={assignPlan}>
                <div className="field">
                  <label htmlFor="assign-plan">Plan</label>
                  <select
                    id="assign-plan"
                    value={planForm.plan_id}
                    onChange={(e) => setPlanForm({ ...planForm, plan_id: e.target.value })}
                  >
                    {plans.map((plan) => (
                      <option key={plan.id} value={plan.id}>
                        {plan.name} — ₹{inr(plan.price_paise / 100)}/mo,{' '}
                        {plan.included_minutes
                          ? `${inr(plan.included_minutes)} min`
                          : 'custom minutes'}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="field">
                  <label htmlFor="assign-months">Months</label>
                  <input
                    id="assign-months"
                    type="number"
                    min="1"
                    max="12"
                    value={planForm.months}
                    onChange={(e) => setPlanForm({ ...planForm, months: e.target.value })}
                  />
                </div>
                <div className="field">
                  <label htmlFor="assign-minutes">Included minutes override</label>
                  <input
                    id="assign-minutes"
                    type="number"
                    min="0"
                    value={planForm.included_minutes}
                    placeholder="Leave blank for list value"
                    onChange={(e) =>
                      setPlanForm({ ...planForm, included_minutes: e.target.value })
                    }
                  />
                </div>
                <div className="field">
                  <label htmlFor="assign-price">Price override (₹, incl. GST)</label>
                  <input
                    id="assign-price"
                    type="number"
                    min="0"
                    step="0.01"
                    value={planForm.price}
                    placeholder="Leave blank for list price"
                    onChange={(e) => setPlanForm({ ...planForm, price: e.target.value })}
                  />
                  <p className="hint">
                    A non-zero price issues a paid invoice for this period. Zero is a comp.
                  </p>
                </div>
                <button type="submit" className="btn primary" disabled={busy === 'plan'}>
                  {busy === 'plan' ? 'Assigning…' : 'Assign plan'}
                </button>
              </form>
            </div>
          </div>

          <div className="card" style={{ marginTop: 18 }}>
            <div className="card-h">
              <h3>Recent invoices</h3>
              <span>latest 10</span>
            </div>
            <table className="tbl">
              <thead>
                <tr>
                  <th>Invoice</th>
                  <th>Description</th>
                  <th>Issued</th>
                  <th>Total</th>
                </tr>
              </thead>
              <tbody>
                {(detail.invoices || []).length === 0 && (
                  <tr>
                    <td colSpan={4} className="table-state">
                      No invoices for this organization yet.
                    </td>
                  </tr>
                )}
                {(detail.invoices || []).map((invoice) => (
                  <tr key={invoice.id}>
                    <td className="mono">{invoice.number}</td>
                    <td>{invoice.description}</td>
                    <td className="mono">{fmtDate(invoice.issued_at)}</td>
                    <td className="mono">₹{inr(invoice.total_paise / 100)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
