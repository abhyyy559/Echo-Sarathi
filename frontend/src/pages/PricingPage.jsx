import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import '../od-pricing.css';
import ThemeToggle from '../components/ThemeToggle.jsx';

/* Public pricing — plans with included minutes plus a prepaid overage wallet.
 *
 * Rates mirror backend/app/services/plans.py (PLANS) and the pack table in
 * backend/app/services/billing.py. Change both sides together or checkout and
 * this page drift. All prices are GST-inclusive.
 */
const PLANS = [
  {
    id: 'free',
    name: 'Free',
    price: 0,
    minutes: 0,
    rate: 3.0,
    seats: 1,
    agents: 3,
    concurrent: 2,
    retention: '30 days',
    tag: 'Kick the tyres with 10 trial minutes in the wallet. No card required.',
    feats: [
      '10 free trial minutes',
      '1 seat · 3 agents · 2 concurrent calls',
      'Playground tests always free',
      '30-day transcript retention',
    ],
    cta: 'Start free',
  },
  {
    id: 'starter',
    name: 'Starter',
    price: 2990,
    minutes: 1000,
    rate: 3.0,
    seats: 3,
    agents: 3,
    concurrent: 2,
    retention: '90 days',
    tag: 'A single team running daily follow-ups and first pilots.',
    feats: [
      '1,000 included minutes / month',
      '3 seats · 3 agents · 2 concurrent',
      'Overage at ₹3.00 / minute',
      '90-day transcript retention',
      'GST invoices + email support',
    ],
    cta: 'Choose Starter',
  },
  {
    id: 'growth',
    name: 'Growth',
    price: 8700,
    minutes: 3000,
    rate: 2.9,
    seats: 10,
    agents: 10,
    concurrent: 5,
    retention: '180 days',
    tag: 'Daily calling for a department, with headroom for retries.',
    feats: [
      '3,000 included minutes / month',
      '10 seats · 10 agents · 5 concurrent',
      'Overage at ₹2.90 / minute',
      '180-day transcript retention',
      'Priority email support',
    ],
    cta: 'Choose Growth',
  },
  {
    id: 'scale',
    name: 'Scale',
    price: 28000,
    minutes: 10000,
    rate: 2.8,
    seats: 30,
    agents: 30,
    concurrent: 15,
    retention: '365 days',
    tag: 'High-volume campaigns across several agents and teams.',
    feats: [
      '10,000 included minutes / month',
      '30 seats · 30 agents · 15 concurrent',
      'Overage at ₹2.80 / minute',
      '365-day transcript retention',
      'Onboarding + priority support',
    ],
    cta: 'Choose Scale',
  },
];

const PAID_PLANS = PLANS.filter((plan) => plan.id !== 'free');

/* Cheapest self-serve way to cover N connected minutes: every plan's list
 * price plus overage at its own rate. The minimum is monotone in minutes, so a
 * simple scan is enough — no dynamic programming needed here. */
function quote(minutes) {
  let best = null;
  for (const plan of PAID_PLANS) {
    const overage = Math.max(0, minutes - plan.minutes);
    const cost = plan.price + overage * plan.rate;
    if (!best || cost < best.cost) best = { plan, cost, overage };
  }
  return best;
}

const fmt = (n) => Number(n).toLocaleString('en-IN');

export default function PricingPage() {
  const [navScrolled, setNavScrolled] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [minutes, setMinutes] = useState(3000);
  const rootRef = React.useRef(null);

  useEffect(() => {
    const onScroll = () => setNavScrolled(window.scrollY > 40);
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  useEffect(() => {
    const root = rootRef.current;
    if (!root || !('IntersectionObserver' in window)) {
      root?.querySelectorAll('.reveal').forEach((el) => el.classList.add('in'));
      return undefined;
    }
    const io = new IntersectionObserver(
      (entries) => entries.forEach((e) => {
        if (e.isIntersecting) { e.target.classList.add('in'); io.unobserve(e.target); }
      }),
      { threshold: 0.12 },
    );
    root.querySelectorAll('.reveal').forEach((el) => io.observe(el));
    return () => io.disconnect();
  }, []);

  const estimate = quote(minutes);

  return (
    <div className="od-pricing" ref={rootRef}>
      <nav id="mainNav" className={navScrolled ? 'scrolled' : ''}>
        <div className="nav-inner">
          <div className="nav-left">
            <Link to="/" className="logo" style={{ display: 'flex', alignItems: 'center', gap: 12, textDecoration: 'none' }}>
              <svg className="logo-mark" width="38" height="22" viewBox="0 0 46 26" fill="none" aria-hidden="true"><circle className="lm-src" cx="6" cy="13" r="2.2" /><path className="lm-a l1" d="M10.02 7.27 A7 7 0 0 1 10.02 18.73" /><path className="lm-a l2" d="M12.88 3.17 A12 12 0 0 1 12.88 22.83" /><circle className="lm-echo" cx="40" cy="13" r="2.2" /><path className="lm-b r1" d="M35.98 7.27 A7 7 0 0 0 35.98 18.73" /><path className="lm-b r2" d="M33.12 3.17 A12 12 0 0 0 33.12 22.83" /></svg>
              <span className="logo-text">Echo Sarathi</span>
            </Link>
            <Link to="/#product" className="nav-link">Product</Link>
            <Link to="/#usecases" className="nav-link">Use Cases</Link>
            <Link to="/#demo" className="nav-link">Demo</Link>
          </div>
          <div className="nav-right">
            <Link to="/roadmap" className="nav-link">Roadmap</Link>
            <ThemeToggle />
            <Link to="/login" className="nav-cta">Start free</Link>
            <div className={`hamburger${mobileOpen ? ' open' : ''}`} role="button" tabIndex={0} aria-label="Menu"
              onClick={() => setMobileOpen((v) => !v)}
              onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') setMobileOpen((v) => !v); }}>
              <span></span><span></span><span></span>
            </div>
          </div>
        </div>
      </nav>
      <div className={`mobile-drawer${mobileOpen ? ' open' : ''}`} onClick={() => setMobileOpen(false)}>
        <Link to="/#product">Product</Link>
        <Link to="/#usecases">Use Cases</Link>
        <Link to="/#demo">Demo</Link>
        <Link to="/roadmap">Roadmap</Link>
        <Link to="/login" className="drawer-cta">Start free</Link>
      </div>

      <main className="page">
        <span className="kick reveal">Plans &amp; minutes</span>
        <h1 className="reveal">Built for real conversations.<br />Priced per minute.</h1>
        <p className="sub reveal">
          Pick a monthly plan with included connected minutes. Run out mid-month
          and the prepaid wallet covers overage at your plan's rate — metered to
          the second, billed only when the call connects.
        </p>

        <div className="trial-strip reveal">
          <span><b>10 minutes free</b> on signup — a real pilot, not a demo</span>
          <span>·</span>
          <span>No card required</span>
          <span>·</span>
          <span>Playground time always free</span>
        </div>

        <div className="grid packs">
          {PLANS.map((plan, i) => {
            const featured = plan.id === 'growth';
            return (
              <div key={plan.id} className={`pcard reveal${featured ? ' featured' : ''}`} style={{ transitionDelay: `${i * 0.07}s` }}>
                {featured && <span className="rec"><i></i>Most popular</span>}
                <div className="tier">
                  <i style={featured ? { background: 'var(--pearl)' } : undefined}></i>
                  {plan.name}
                </div>
                <div className="pline">
                  <span className="amt">{plan.price === 0 ? '₹0' : `₹${fmt(plan.price)}`}</span>
                  <span className="unit">{plan.price === 0 ? 'to start' : '/ month'}</span>
                </div>
                <p className="ptag">
                  {plan.minutes > 0
                    ? `${fmt(plan.minutes)} included minutes · ₹${plan.rate.toFixed(2)}/min overage. `
                    : 'Trial minutes in the wallet, then ₹3.00/min. '}
                  {plan.tag}
                </p>
                <ul className="feats">
                  {plan.feats.map((feat) => (
                    <li key={feat}>
                      <svg viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12" /></svg>
                      <span>{feat}</span>
                    </li>
                  ))}
                </ul>
                <Link to="/login" className={`cta${featured ? ' cta-solid' : ''}`}>
                  {plan.cta}
                </Link>
              </div>
            );
          })}
        </div>

        <div className="ent-strip reveal">
          <div>
            <div className="ent-k">Enterprise</div>
            <p>
              30,000+ minutes, custom seats and concurrency, SLA and security
              review support, annual invoicing with a purchase order.
            </p>
          </div>
          <a className="cta" href="mailto:hello@echosarathi.ai?subject=Enterprise%20plan">
            Talk to sales
          </a>
        </div>

        <div className="est reveal" style={{ maxWidth: 580, margin: '44px auto 0', textAlign: 'left' }}>
          <span className="est-h">Estimate your monthly bill</span>
          <input
            type="range"
            min="100"
            max="20000"
            step="100"
            value={minutes}
            onChange={(e) => setMinutes(Number(e.target.value))}
            aria-label="Estimated connected minutes per month"
          />
          <div className="est-row">
            <span className="est-min"><b>{fmt(minutes)}</b> minutes / mo</span>
            <span className="est-cost"><span>₹{fmt(estimate.cost)}</span> <small>/ month est.</small></span>
          </div>
          <div style={{ fontSize: 12, color: 'var(--dim)', marginTop: 10, lineHeight: 1.6 }}>
            {estimate.plan.name} plan — {fmt(estimate.plan.minutes)} included minutes
            {estimate.overage > 0
              ? ` + ${fmt(estimate.overage)} overage minutes at ₹${estimate.plan.rate.toFixed(2)}/min.`
              : ', no overage needed.'}{' '}
            Only connected calls consume minutes; unanswered calls are free.
          </div>
        </div>

        <div className="note reveal">
          <span><svg viewBox="0 0 24 24"><rect x="3" y="11" width="18" height="11" rx="2" /><path d="M7 11V7a5 5 0 0 1 10 0v4" /></svg>No card for the free minutes</span>
          <span><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10" /><path d="M12 6v6l4 2" /></svg>Only connected calls are billed</span>
          <span><svg viewBox="0 0 24 24"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" /></svg>Playground time is always free</span>
        </div>

        <div className="mini-cta reveal">
          <h2>Start free. Upgrade when the calls work.</h2>
          <p>
            Create an agent, use the 10 welcome minutes, and move onto a plan
            only when you take it live. Prices are monthly and include 18% GST;
            unused included minutes don't roll over, wallet credit never expires.
          </p>
          <div className="btns">
            <Link to="/login" className="btn-p">Start free</Link>
            <Link to="/#demo" className="btn-g">See the demo</Link>
          </div>
        </div>
      </main>

      <footer>
        <div className="f-in">
          <span>&copy; {new Date().getFullYear()} Echo Sarathi Labs</span>
          <div className="f-links">
            <Link to="/">Home</Link>
            <Link to="/roadmap">Roadmap</Link>
            <Link to="/login">Sign in</Link>
            <a href="mailto:hello@echosarathi.ai">hello@echosarathi.ai</a>
          </div>
        </div>
      </footer>
    </div>
  );
}
