import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { billingApi, getStoredUser } from '../api.js';

const KIND_LABELS = {
  grant: { cls: 'ok', label: 'Welcome credit' },
  purchase: { cls: 'cyan', label: 'Top-up' },
  usage: { cls: 'warn', label: 'Call usage' },
  adjustment: { cls: 'purple', label: 'Adjustment' },
};

let razorpayLoader = null;

/** Injects the Razorpay checkout script once; resolves when it is ready. */
function loadRazorpay() {
  if (window.Razorpay) return Promise.resolve();
  if (razorpayLoader) return razorpayLoader;
  razorpayLoader = new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = 'https://checkout.razorpay.com/v1/checkout.js';
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => {
      razorpayLoader = null;
      reject(new Error('Could not load the payment window. Check your connection.'));
    };
    document.body.appendChild(script);
  });
  return razorpayLoader;
}

function inr(value, digits = 2) {
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

function daysUntil(value) {
  if (!value) return 0;
  return Math.ceil((new Date(value).getTime() - Date.now()) / 86_400_000);
}

const EMPTY_PROFILE = {
  legal_name: '',
  gstin: '',
  billing_email: '',
  billing_address: '',
  billing_state: '',
};

export default function CreditsPage() {
  const user = getStoredUser();
  const canManage = Boolean(user && ['owner', 'admin'].includes(user.role));

  const [data, setData] = useState(null);
  const [invoices, setInvoices] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(null);
  const [notice, setNotice] = useState(null);
  const [profile, setProfile] = useState(EMPTY_PROFILE);
  const [savingProfile, setSavingProfile] = useState(false);

  function load() {
    setLoading(true);
    setError(null);
    Promise.all([
      billingApi.summary(),
      billingApi.invoices().catch(() => ({ invoices: [] })),
    ])
      .then(([summary, invoiceData]) => {
        setData(summary);
        setInvoices(Array.isArray(invoiceData.invoices) ? invoiceData.invoices : []);
        setProfile({ ...EMPTY_PROFILE, ...(summary.billing_profile || {}) });
      })
      .catch((e) => setError(e.message || String(e)))
      .finally(() => setLoading(false));
  }

  useEffect(load, []);

  /** Open Razorpay for any order (plan or top-up) and verify on success. */
  async function startCheckout(order, description, successMessage) {
    await loadRazorpay();
    const rzp = new window.Razorpay({
      key: order.key_id,
      amount: order.amount,
      currency: order.currency,
      name: 'Echo Sarathi',
      description,
      order_id: order.order_id,
      theme: { color: '#5b8cff' },
      modal: {
        ondismiss: () => {
          setBusy(null);
          setNotice('Payment cancelled — nothing was charged.');
        },
      },
      handler: async (response) => {
        try {
          const next = await billingApi.verify({
            razorpay_order_id: response.razorpay_order_id,
            razorpay_payment_id: response.razorpay_payment_id,
            razorpay_signature: response.razorpay_signature,
            pack_id: order.pack_id,
          });
          setData(next);
          setNotice(successMessage(next));
          load();
        } catch (e) {
          setNotice(
            e.message ||
              'Payment succeeded but verification failed. Contact support with your payment id — you will not be charged twice.'
          );
        } finally {
          setBusy(null);
        }
      },
    });
    rzp.on('payment.failed', (resp) => {
      setBusy(null);
      setNotice(`Payment failed: ${resp?.error?.description || 'nothing was charged.'}`);
    });
    rzp.open();
  }

  function subscribe(plan) {
    setBusy(plan.id);
    setNotice(null);
    billingApi
      .subscribe(plan.id)
      .then(async (res) => {
        if (res.mode === 'manual') {
          setData(res);
          setNotice(`${plan.name} plan is active. Invoice ${res.invoice?.number || ''} issued.`);
          load();
          setBusy(null);
          return;
        }
        await startCheckout(
          res,
          `${plan.name} plan · ${Number(res.minutes).toLocaleString('en-IN')} included minutes`,
          (next) =>
            `${plan.name} plan is active — invoice ${next.invoice?.number || 'issued'} sent to your billing email.`
        );
      })
      .catch((e) => {
        setBusy(null);
        setNotice(e.message || String(e));
      });
  }

  function buy(pack) {
    if (data && data.manual_payments_enabled && !data.checkout_enabled) {
      setBusy(pack.id);
      billingApi
        .topup(pack.id)
        .then((next) => {
          setData(next);
          setNotice(`${pack.name} pack added — ${pack.minutes} minutes credited.`);
          load();
        })
        .catch((e) => setNotice(e.message || String(e)))
        .finally(() => setBusy(null));
      return;
    }
    setBusy(pack.id);
    setNotice(null);
    billingApi
      .checkout(pack.id)
      .then((order) =>
        startCheckout(
          order,
          `${order.pack_name} pack · ${order.minutes} minutes`,
          () => `${pack.name} pack added — ${pack.minutes} minutes credited.`
        )
      )
      .catch((e) => {
        setBusy(null);
        setNotice(e.message || String(e));
      });
  }

  function cancelPlan() {
    if (!window.confirm('Stop renewing this plan? You keep the paid period until it ends.')) {
      return;
    }
    setBusy('cancel');
    billingApi
      .cancel()
      .then((next) => {
        setData(next);
        setNotice('Renewal stopped — the plan stays active until the period ends.');
      })
      .catch((e) => setNotice(e.message || String(e)))
      .finally(() => setBusy(null));
  }

  function saveProfile(e) {
    e.preventDefault();
    setSavingProfile(true);
    billingApi
      .updateProfile(profile)
      .then((saved) => {
        setProfile({ ...EMPTY_PROFILE, ...saved });
        setNotice('Billing details saved — they apply to future invoices.');
      })
      .catch((err) => setError(err.message || String(err)))
      .finally(() => setSavingProfile(false));
  }

  const balance = data ? Number(data.balance_rupees) : 0;
  const minutes = data ? Number(data.available_minutes_remaining) : 0;
  const lowBalance = Boolean(data && data.low_balance);
  const checkoutOn = Boolean(data && data.checkout_enabled);
  const manualOn = Boolean(data && data.manual_payments_enabled);
  const paymentsOn = checkoutOn || manualOn;
  const ledger = data && Array.isArray(data.ledger) ? data.ledger : [];
  const packs = data && Array.isArray(data.packs) ? data.packs : [];
  const planCatalog = data && Array.isArray(data.plan_catalog) ? data.plan_catalog : [];
  const subscription = data ? data.subscription : null;
  const currentPlan = data ? data.plan : null;
  const includedTotal = data ? Number(data.included_minutes_total) : 0;
  const includedUsed = data ? Number(data.included_minutes_used) : 0;
  const includedPct = includedTotal > 0 ? Math.min(100, (includedUsed / includedTotal) * 100) : 0;
  const renewWindow = subscription ? daysUntil(subscription.period_end) <= 7 : false;

  return (
    <div>
      <div className="page-head">
        <div>
          <h2 className="page-title">Billing &amp; credits</h2>
          <p className="page-sub">
            A monthly plan with included minutes, plus a prepaid wallet for overage.
            Only connected calls consume minutes.
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
          <span className="spinner" /> Loading billing…
        </div>
      )}

      {data && (
        <>
          {lowBalance && (
            <div className="banner banner-error" style={{ marginBottom: 16 }}>
              <strong>Your balance is running low.</strong> Campaigns stop dialing
              when included minutes and wallet credit both run out — top up or
              renew to keep calls going.
            </div>
          )}

          {notice && (
            <div className="banner banner-success" style={{ marginBottom: 16 }}>
              {notice}
            </div>
          )}

          {/* --- current plan ------------------------------------------------ */}
          <div className="card plan-hero">
            <div className="plan-hero-main">
              <div className="plan-hero-top">
                <div>
                  <div className="lbl">Current plan</div>
                  <div className="plan-hero-name">
                    {currentPlan ? currentPlan.name : 'Free'}
                    {subscription && (
                      <span className={`badge ${subscription.cancel_at_period_end ? 'warn' : 'ok'}`}>
                        {subscription.cancel_at_period_end ? 'Ends soon' : 'Active'}
                      </span>
                    )}
                  </div>
                  <div className="plan-hero-sub">
                    {subscription
                      ? `${fmtDate(subscription.period_start)} → ${fmtDate(subscription.period_end)} · ₹${inr(subscription.price_paise / 100, 0)} incl. GST`
                      : `₹${inr(currentPlan ? currentPlan.price_paise / 100 : 0, 0)} · 10 welcome minutes in the wallet`}
                  </div>
                </div>
                <div className="plan-hero-actions">
                  {subscription && renewWindow && !subscription.cancel_at_period_end && (
                    <button
                      type="button"
                      className="btn primary"
                      disabled={busy !== null}
                      onClick={() => subscribe(currentPlan)}
                    >
                      {busy === currentPlan.id ? 'Opening…' : 'Renew plan'}
                    </button>
                  )}
                  {subscription && !subscription.cancel_at_period_end && (
                    <button
                      type="button"
                      className="btn btn-secondary btn-sm"
                      disabled={busy !== null}
                      onClick={cancelPlan}
                    >
                      Cancel renewal
                    </button>
                  )}
                </div>
              </div>

              <div className="usage-line">
                <div className="usage-line-label">
                  <span>Included minutes this period</span>
                  <span>
                    <b>{inr(includedUsed, 1)}</b> / {inr(includedTotal, 0)} min
                  </span>
                </div>
                <div className="progress">
                  <b style={{ width: `${includedPct}%` }} />
                </div>
                <div className="usage-line-foot">
                  {includedTotal > 0
                    ? `${inr(data.included_minutes_remaining, 1)} included minutes left, then ₹${inr(
                        data.overage_per_minute_paise / 100
                      )}/min from the wallet.`
                    : `No included minutes on this plan — calls use the wallet at ₹${inr(
                        data.overage_per_minute_paise / 100
                      )}/min.`}
                </div>
              </div>
            </div>
          </div>

          <div className="grid g5" style={{ marginTop: 18 }}>
            <div className="card stat">
              <div className="lbl">Available minutes</div>
              <div className="num">{inr(minutes, 1)}</div>
              <div className="foot">
                <span className={`badge ${lowBalance ? 'crit' : 'ok'}`}>
                  {lowBalance ? 'Top up soon' : data.can_dial ? 'Ready to dial' : 'Dialing paused'}
                </span>
              </div>
            </div>
            <div className="card stat">
              <div className="lbl">Wallet balance</div>
              <div className="num">₹{inr(balance)}</div>
              <div className="foot">{inr(data.wallet_minutes_remaining, 1)} overage minutes</div>
            </div>
            <div className="card stat">
              <div className="lbl">Spent this month</div>
              <div className="num">₹{inr(data.spent_this_month_rupees)}</div>
              <div className="foot">overage, connected calls only</div>
            </div>
            <div className="card stat">
              <div className="lbl">Minutes this month</div>
              <div className="num">{inr(data.minutes_used_this_month, 1)}</div>
              <div className="foot">across all agents</div>
            </div>
            <div className="card stat">
              <div className="lbl">Overage rate</div>
              <div className="num">₹{inr(data.overage_per_minute_paise / 100)}</div>
              <div className="foot">per connected minute, billed per second</div>
            </div>
          </div>

          {/* --- plans ------------------------------------------------------- */}
          <div className="card" style={{ marginTop: 18 }}>
            <div className="card-h">
              <h3>Plans</h3>
              <span>monthly · prices include 18% GST</span>
            </div>
            <div className="plan-grid">
              {planCatalog.map((plan) => {
                const isCurrent = currentPlan && plan.id === currentPlan.id;
                const isEnterprise = Boolean(plan.custom);
                const renewLater = isCurrent && subscription && !renewWindow;
                return (
                  <div
                    key={plan.id}
                    className={`plan-card${isCurrent ? ' current' : ''}${plan.id === 'growth' ? ' featured' : ''}`}
                  >
                    {isCurrent && <span className="plan-flag">Current</span>}
                    {!isCurrent && plan.id === 'growth' && (
                      <span className="plan-flag">Most popular</span>
                    )}
                    <div className="plan-name">{plan.name}</div>
                    <div className="plan-price">
                      {isEnterprise ? (
                        <>Custom</>
                      ) : (
                        <>
                          ₹{inr(plan.price_paise / 100, 0)}
                          <small>/month</small>
                        </>
                      )}
                    </div>
                    <div className="plan-minutes">
                      {isEnterprise
                        ? '30,000+ minutes, on contract'
                        : plan.included_minutes > 0
                          ? `${Number(plan.included_minutes).toLocaleString('en-IN')} included minutes`
                          : '10 trial minutes on signup'}
                    </div>
                    <div className="plan-limits">
                      {plan.max_users >= 999 ? 'Custom' : plan.max_users} seats ·{' '}
                      {plan.max_agents >= 999 ? 'Custom' : plan.max_agents} agents ·{' '}
                      {plan.max_concurrent_calls} concurrent
                    </div>
                    <ul className="plan-feats">
                      {(plan.features || []).slice(0, 4).map((feature) => (
                        <li key={feature}>{feature}</li>
                      ))}
                    </ul>
                    {isEnterprise ? (
                      <a className="btn btn-secondary btn-block" href="mailto:hello@echosarathi.ai?subject=Enterprise%20plan">
                        Talk to sales
                      </a>
                    ) : plan.id === 'free' ? (
                      <button type="button" className="btn btn-secondary btn-block" disabled>
                        {isCurrent ? 'Included' : 'Free tier'}
                      </button>
                    ) : (
                      <button
                        type="button"
                        className={`btn ${plan.id === 'growth' ? 'primary' : 'btn-secondary'} btn-block`}
                        disabled={!paymentsOn || busy !== null || (isCurrent && !renewWindow) || (!canManage && !!user)}
                        onClick={() => subscribe(plan)}
                        title={
                          !paymentsOn
                            ? 'Online payments are not enabled in this environment'
                            : isCurrent && !renewWindow
                              ? 'Renewals open in the last 7 days of the period'
                              : ''
                        }
                      >
                        {busy === plan.id
                          ? 'Opening…'
                          : renewLater
                            ? 'Current plan'
                            : isCurrent
                              ? 'Renew plan'
                              : `Choose ${plan.name}`}
                      </button>
                    )}
                  </div>
                );
              })}
            </div>
            <div className="plan-footnote">
              Changing plans starts a new period immediately and replaces the
              current one — there is no proration. Included minutes do not roll
              over; wallet credits never expire.
              {!canManage && user ? ' Only owners and admins can change billing.' : ''}
            </div>
          </div>

          {/* --- top-ups ----------------------------------------------------- */}
          <div className="card" style={{ marginTop: 18 }}>
            <div className="card-h">
              <h3>Top up the wallet</h3>
              <span>overage credit · never expires</span>
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
                    disabled={!paymentsOn || busy !== null || !canManage}
                    onClick={() => buy(pack)}
                    title={
                      !paymentsOn
                        ? 'Online payments are not enabled in this environment'
                        : !canManage
                          ? 'Only owners and admins can top up'
                          : ''
                    }
                  >
                    {busy === pack.id ? 'Opening…' : `Buy ${pack.name}`}
                  </button>
                </div>
              ))}
            </div>
            {!paymentsOn && (
              <div style={{ padding: '0 20px 18px', fontSize: 12.5, color: 'var(--dim)' }}>
                Online checkout is not enabled in this environment yet. Nothing is charged
                here and no credits are added automatically. To buy a pack,
                write to <a href="mailto:hello@echosarathi.ai">hello@echosarathi.ai</a>.
              </div>
            )}
          </div>

          {/* --- invoices ---------------------------------------------------- */}
          <div className="card" style={{ marginTop: 18 }}>
            <div className="card-h">
              <h3>Invoices</h3>
              <span>GST invoices for plans and top-ups</span>
            </div>
            <table className="tbl">
              <thead>
                <tr>
                  <th>Invoice</th>
                  <th>Description</th>
                  <th>Issued</th>
                  <th>Total (incl. GST)</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {invoices.length === 0 && (
                  <tr>
                    <td colSpan={5} className="table-state">
                      No invoices yet — a GST invoice is issued for every plan purchase and top-up.
                    </td>
                  </tr>
                )}
                {invoices.map((invoice) => (
                  <tr key={invoice.id}>
                    <td className="mono">{invoice.number}</td>
                    <td>{invoice.description}</td>
                    <td className="mono">{fmtDate(invoice.issued_at)}</td>
                    <td className="mono">₹{inr(invoice.total_paise / 100)}</td>
                    <td style={{ textAlign: 'right' }}>
                      <Link to={`/invoices/${invoice.id}`} className="btn btn-ghost btn-sm">
                        View
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* --- profile + explainer ----------------------------------------- */}
          <div className="grid g2" style={{ marginTop: 18 }}>
            <div className="card">
              <div className="card-h">
                <h3>Billing details</h3>
                <span>printed on future invoices</span>
              </div>
              <form className="billing-form" onSubmit={saveProfile}>
                <div className="field">
                  <label htmlFor="billing-legal-name">Registered legal name</label>
                  <input
                    id="billing-legal-name"
                    type="text"
                    value={profile.legal_name}
                    placeholder="Sunrise Academy Pvt Ltd"
                    disabled={!canManage}
                    onChange={(e) => setProfile({ ...profile, legal_name: e.target.value })}
                  />
                </div>
                <div className="field">
                  <label htmlFor="billing-gstin">GSTIN</label>
                  <input
                    id="billing-gstin"
                    type="text"
                    value={profile.gstin}
                    placeholder="29ABCDE1234F1Z5"
                    disabled={!canManage}
                    onChange={(e) => setProfile({ ...profile, gstin: e.target.value.toUpperCase() })}
                  />
                </div>
                <div className="field">
                  <label htmlFor="billing-email">Billing email</label>
                  <input
                    id="billing-email"
                    type="email"
                    value={profile.billing_email}
                    placeholder="accounts@company.com"
                    disabled={!canManage}
                    onChange={(e) => setProfile({ ...profile, billing_email: e.target.value })}
                  />
                </div>
                <div className="field">
                  <label htmlFor="billing-state">State (place of supply)</label>
                  <input
                    id="billing-state"
                    type="text"
                    value={profile.billing_state}
                    placeholder="Karnataka"
                    disabled={!canManage}
                    onChange={(e) => setProfile({ ...profile, billing_state: e.target.value })}
                  />
                </div>
                <div className="field">
                  <label htmlFor="billing-address">Billing address</label>
                  <textarea
                    id="billing-address"
                    rows={3}
                    value={profile.billing_address}
                    placeholder="Street, city, PIN"
                    disabled={!canManage}
                    onChange={(e) => setProfile({ ...profile, billing_address: e.target.value })}
                  />
                </div>
                <button type="submit" className="btn primary" disabled={!canManage || savingProfile}>
                  {savingProfile ? 'Saving…' : 'Save billing details'}
                </button>
              </form>
            </div>

            <div className="card">
              <div className="card-h">
                <h3>How billing works</h3>
                <span>simple, prepaid</span>
              </div>
              <div style={{ padding: '6px 20px 18px' }}>
                <ul className="credit-rules">
                  <li>
                    <b>Included minutes come first.</b> Every connected call consumes
                    plan minutes; the wallet is only touched once they run out.
                  </li>
                  <li>
                    <b>Only connected calls are billed.</b> Busy, no-answer and
                    failed legs cost you nothing.
                  </li>
                  <li>
                    <b>Metered to the second.</b> A 47-second call is 47 seconds at
                    the plan&apos;s overage rate — never rounded up to a minute.
                  </li>
                  <li>
                    <b>Playground time is free.</b> Test any agent version in the
                    browser without spending a paisa.
                  </li>
                  <li>
                    <b>Campaigns pause themselves.</b> When payable minutes run out
                    the dialer stops placing legs; they resume after a top-up or renewal.
                  </li>
                </ul>
              </div>
            </div>
          </div>

          <div className="card" style={{ marginTop: 18 }}>
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
        </>
      )}
    </div>
  );
}
