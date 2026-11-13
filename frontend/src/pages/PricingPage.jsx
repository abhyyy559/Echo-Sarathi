import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import PublicLayout, { PublicFaq } from '../components/PublicLayout.jsx';

// Keep catalogue amounts aligned with plans.py; this page never starts checkout.
const PLANS = [
  { id: 'free', name: 'Free', price: 0, minutes: 0, rate: 3.0, seats: 1, agents: 3, concurrent: 2, retention: '30 days', tag: 'Explore with an eligible trial account.' },
  { id: 'starter', name: 'Starter', price: 2990, minutes: 1000, rate: 3.0, seats: 3, agents: 3, concurrent: 2, retention: '90 days', tag: 'A pilot or a single team’s follow-ups.' },
  { id: 'growth', name: 'Growth', price: 8700, minutes: 3000, rate: 2.9, seats: 10, agents: 10, concurrent: 5, retention: '180 days', tag: 'A department’s regular calling workflow.' },
  { id: 'scale', name: 'Scale', price: 28000, minutes: 10000, rate: 2.8, seats: 30, agents: 30, concurrent: 15, retention: '365 days', tag: 'Larger allowances across teams and agents.' },
];
const PAID_PLANS = PLANS.filter((plan) => plan.id !== 'free');
const fmt = (n) => Number(n).toLocaleString('en-IN');

function quote(minutes) {
  let best = null;
  for (const plan of PAID_PLANS) {
    const overage = Math.max(0, minutes - plan.minutes);
    const cost = plan.price + overage * plan.rate;
    if (!best || cost < best.cost) best = { plan, cost, overage };
  }
  return best;
}

const FAQS = [
  { question: 'Are the displayed prices inclusive of GST?', answer: <p>Yes. The listed monthly prices and overage rates include 18% GST. The estimate uses those listed amounts; it does not add tax again.</p> },
  { question: 'How do the plan allowance and wallet work together?', answer: <p>Included minutes are used first. Once the allowance is exhausted, phone usage draws from your prepaid wallet at the plan’s overage rate. The Free plan has no monthly allowance, so usage draws from its trial or prepaid wallet balance.</p> },
  { question: 'Do unused minutes or wallet credit roll over?', answer: <p>Unused included minutes do not roll over to the next monthly period. Wallet credit is separate prepaid value, does not expire, and is not reset with the monthly allowance.</p> },
  { question: 'What is included in the trial?', answer: <p>The catalogue provides 10 trial minutes in the wallet for eligible new accounts, with no card required for the trial. This is a one-time trial, not 10 minutes every month. Public signup is not open; an existing account or invitation is required.</p> },
  { question: 'Are Playground tests the same as phone calls?', answer: <p>No. Browser voice and text testing in the <Link to="/playground">Playground</Link> is separate from billable phone testing. A phone-mode test places an actual call, requires authorization, and uses the applicable phone allowance or wallet balance.</p> },
  { question: 'Can I buy a plan from this page?', answer: <p>This page explains the catalogue and estimates usage; it does not create a subscription or charge you. <Link to="/login">Sign in</Link> to review the options available to your organization in Billing &amp; credits. Account eligibility and payment availability still apply.</p> },
];

export default function PricingPage() {
  const [minutes, setMinutes] = useState(3000);
  const estimate = quote(minutes);

  return (
    <PublicLayout>
      <section className="es-public-page-intro" aria-labelledby="es-public-pricing-heading">
        <p className="es-public-context">Pricing</p>
        <h1 id="es-public-pricing-heading">A plan for your calls.<br />Room for the follow-up.</h1>
        <div className="es-public-intro-row">
          <p className="es-public-lead">Choose a monthly allowance. Keep prepaid wallet credit for overage. See the two separately, before you commit.</p>
          <div><Link className="es-public-button" to="/login">Open workspace</Link><p className="es-public-access-note">Existing account or invitation required.</p></div>
        </div>
      </section>

      <section className="es-public-plan-section" aria-labelledby="es-public-plans-title">
        <div className="es-public-inline-heading"><h2 id="es-public-plans-title">Compare monthly plans</h2><p>All listed prices include 18% GST.</p></div>
        <p className="es-public-table-help" id="es-public-plan-help">Scroll the comparison horizontally on smaller screens. Plan limits describe the catalogue, not guaranteed calling capacity.</p>
        <div className="es-public-table-scroll" role="region" aria-labelledby="es-public-plans-title" aria-describedby="es-public-plan-help" tabIndex={0}>
          <table className="es-public-plan-table">
            <caption className="es-public-sr-only">Monthly fees, included minutes, overage rates, and account limits for Free, Starter, Growth, and Scale.</caption>
            <thead><tr><th scope="col">Monthly plan</th>{PLANS.map((plan) => <th scope="col" key={plan.id}><span>{plan.name}</span><p>{plan.tag}</p></th>)}</tr></thead>
            <tbody>
              <tr className="es-public-price-row"><th scope="row">Monthly price</th>{PLANS.map((plan) => <td key={plan.id}>₹{fmt(plan.price)}<span>/ month</span></td>)}</tr>
              <tr><th scope="row">Included minutes <span>Each month</span></th>{PLANS.map((plan) => <td key={plan.id}>{fmt(plan.minutes)}{plan.id === 'free' && <span>10 trial minutes in wallet*</span>}</td>)}</tr>
              <tr><th scope="row">Overage <span>Per minute</span></th>{PLANS.map((plan) => <td key={plan.id}>₹{plan.rate.toFixed(2)}</td>)}</tr>
              <tr><th scope="row">Team seats</th>{PLANS.map((plan) => <td key={plan.id}>{plan.seats}</td>)}</tr>
              <tr><th scope="row">Agents</th>{PLANS.map((plan) => <td key={plan.id}>{plan.agents}</td>)}</tr>
            </tbody>
          </table>
        </div>
        <div className="es-public-plan-notes"><p>*One-time trial for eligible new accounts. Free has no recurring minute allowance. No card required for trial credit.</p><p>Account access remains invitation-based. Review the options available in your workspace before purchasing.</p></div>
        <div className="es-public-enterprise"><div><h3>Enterprise</h3><p>30,000+ minutes, priced on a custom contract. Availability, limits, and support terms need a separate agreement; this is not a self-serve plan.</p></div><Link className="es-public-text-link" to="/login">Sign in to your workspace</Link></div>
      </section>

      <section className="es-public-section es-public-estimator" aria-labelledby="es-public-estimator-title">
        <div className="es-public-estimator-input">
          <p className="es-public-context">Make the numbers concrete.</p>
          <h2 id="es-public-estimator-title">Estimate a month<br />of calling.</h2>
          <p id="es-public-estimate-scope">Compares Starter, Growth, and Scale using list price plus overage. It excludes Free, trial credit, and custom contracts. This is an estimate, not a checkout quote or a capacity promise.</p>
          <div className="es-public-range-heading"><label htmlFor="es-public-minutes">Monthly phone minutes</label><output htmlFor="es-public-minutes">{fmt(minutes)}</output></div>
          <input
            id="es-public-minutes"
            className="es-public-range"
            type="range"
            min="100"
            max="20000"
            step="100"
            value={minutes}
            aria-valuetext={`${fmt(minutes)} minutes per month`}
            aria-describedby="es-public-estimate-scope"
            onChange={(event) => setMinutes(Number(event.target.value))}
          />
          <div className="es-public-range-limits" aria-hidden="true"><span>100 minutes</span><span>20,000 minutes</span></div>
          <div className="es-public-minute-options" role="group" aria-label="Example monthly usage">
            {[1000, 3000, 10000].map((value) => <button key={value} type="button" aria-pressed={minutes === value} onClick={() => setMinutes(value)}>{fmt(value)} minutes</button>)}
          </div>
        </div>
        <div className="es-public-estimate-result" aria-live="polite" aria-atomic="true">
          <p>Lowest-cost paid plan for these minutes</p>
          <h3>{estimate.plan.name}</h3>
          <p className="es-public-estimate-amount">₹{fmt(estimate.cost)} <span>/ month estimated</span></p>
          <dl>
            <div><dt>Monthly plan</dt><dd>₹{fmt(estimate.plan.price)}</dd></div>
            <div><dt>Included minutes</dt><dd>{fmt(estimate.plan.minutes)}</dd></div>
            <div><dt>Overage minutes</dt><dd>{fmt(estimate.overage)}</dd></div>
            <div><dt>Overage at ₹{estimate.plan.rate.toFixed(2)}/min</dt><dd>₹{fmt(estimate.overage * estimate.plan.rate)}</dd></div>
          </dl>
          <p>Includes 18% GST. Overage uses prepaid wallet credit at the selected plan’s rate.</p>
        </div>
      </section>

      <section className="es-public-section es-public-billing-notes" aria-labelledby="es-public-billing-notes-title">
        <div className="es-public-section-intro"><h2 id="es-public-billing-notes-title">Know what you<br />are budgeting for.</h2><p>The allowance, the wallet, and operational limits each do a different job.</p></div>
        <div className="es-public-billing-explanations">
          <article><h3>Monthly allowance</h3><p>Included minutes belong to the active plan period. They are consumed before the wallet and do not roll over into the next month.</p></article>
          <article><h3>Prepaid wallet</h3><p>The wallet holds rupee credit, not an extra monthly allowance. The number of overage minutes it covers depends on your current plan’s rate.</p></article>
          <article><h3>Usage and availability</h3><p>The catalogue is based on connected phone usage. Review actual metering and charges in your workspace; this public estimate is not a production billing audit. Phone access and payment availability must be confirmed separately.</p></article>
          <details className="es-public-catalogue-details">
            <summary>Catalogue capacity and retention reference</summary>
            <div className="es-public-answer">
              <p><strong>These are catalogue values, not verified operational guarantees.</strong> Deployment limits can reduce simultaneous calls below a plan’s listed limit. Confirm active capacity and retention behavior before relying on them; upgrading a plan does not prove that capacity is available.</p>
              <div className="es-public-table-scroll" role="region" aria-label="Catalogue capacity and retention values" tabIndex={0}>
                <table className="es-public-reference-table"><caption className="es-public-sr-only">Catalogue reference only, not delivered capacity or a retention guarantee.</caption><thead><tr><th scope="col">Plan</th><th scope="col">Call limit</th><th scope="col">Retention</th></tr></thead><tbody>{PLANS.map((plan) => <tr key={plan.id}><th scope="row">{plan.name}</th><td>{plan.concurrent}</td><td>{plan.retention}</td></tr>)}</tbody></table>
              </div>
              <p>Enterprise limits are subject to its agreement, not this comparison.</p>
            </div>
          </details>
        </div>
      </section>

      <PublicFaq id="es-public-pricing-faq" items={FAQS} />

      <section className="es-public-closing" aria-labelledby="es-public-pricing-closing">
        <div><h2 id="es-public-pricing-closing">Start with a conversation<br />you can review.</h2><p>Explore the workflow before planning your first campaign.</p></div>
        <div><Link className="es-public-button" to="/login">Open workspace</Link><Link className="es-public-text-link" to="/landing#workflow">See how it works</Link></div>
      </section>
    </PublicLayout>
  );
}
