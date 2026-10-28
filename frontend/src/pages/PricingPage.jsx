import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import '../od-pricing.css';
import ThemeToggle from '../components/ThemeToggle.jsx';

/* Pricing — ported from frontend by opendesign/pricing.html.
 * Public page: no auth, no backend calls. Estimator is local state.
 *
 * Rates mirror backend/app/services/billing.py (CREDIT_PACKS + the ₹3.00
 * list price). Change both sides together or the checkout and this page drift.
 */
const PACKS = [
  {
    id: 'starter',
    name: 'Starter',
    minutes: 60,
    price: 180,
    perMin: 3.0,
    tag: 'A short pilot: one campaign, a hundred contacts or fewer.',
  },
  {
    id: 'growth',
    name: 'Growth',
    minutes: 300,
    price: 870,
    perMin: 2.9,
    tag: 'Daily calling for a single team, with headroom for retries.',
  },
  {
    id: 'scale',
    name: 'Scale',
    minutes: 1000,
    price: 2800,
    perMin: 2.8,
    tag: 'High-volume campaigns across several agents and use cases.',
  },
];

/* Cheapest way to cover N connected minutes with whole packs. Overshoot past
 * one max-size pack can never beat a smaller plan, so the window is N..N+999. */
function quote(minutes) {
  const cap = minutes + 999;
  const cost = new Array(cap + 1).fill(Infinity);
  const take = new Array(cap + 1).fill(null);
  cost[0] = 0;
  for (let i = 1; i <= cap; i += 1) {
    for (const pack of PACKS) {
      if (i >= pack.minutes && cost[i - pack.minutes] + pack.price < cost[i]) {
        cost[i] = cost[i - pack.minutes] + pack.price;
        take[i] = pack;
      }
    }
  }
  let bestAt = minutes;
  for (let i = minutes; i <= cap; i += 1) {
    if (cost[i] < cost[bestAt]) bestAt = i;
  }
  const counts = {};
  for (let i = bestAt; i > 0; i -= take[i].minutes) {
    counts[take[i].id] = (counts[take[i].id] || 0) + 1;
  }
  return { total: cost[bestAt], covered: bestAt, counts };
}

const fmt = (n) => n.toLocaleString('en-IN');

export default function PricingPage() {
  const [navScrolled, setNavScrolled] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [minutes, setMinutes] = useState(600);
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
  const effectiveRate = estimate.total / estimate.covered;
  const breakdown = PACKS
    .filter((p) => estimate.counts[p.id])
    .map((p) => `${estimate.counts[p.id]} × ${p.name}`)
    .join(' + ');

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
            <Link to="/playground" className="nav-link">Playground</Link>
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
        <Link to="/playground">Playground</Link>
        <Link to="/roadmap">Roadmap</Link>
        <Link to="/login" className="drawer-cta">Start free</Link>
      </div>

      <main className="page">
        <span className="kick reveal">Credit pricing</span>
        <h1 className="reveal">Pay for conversation.<br />Not for seats.</h1>
        <p className="sub reveal">
          Every account starts with <b>10 free minutes</b>. After that, ₹3.00 per
          connected minute — metered to the second, billed only when the call
          connects. Top up with credits whenever you run low; they never expire.
        </p>

        <div className="trial-strip reveal">
          <span><b>10 minutes free</b> on signup — a real pilot, not a demo</span>
          <span>·</span>
          <span>No card required</span>
          <span>·</span>
          <span>Playground time always free</span>
        </div>

        <div className="grid packs">
          {PACKS.map((pack, i) => (
            <div key={pack.id} className={`pcard reveal${i === 1 ? ' featured' : ''}`} style={{ transitionDelay: `${i * 0.08}s` }}>
              {i === 1 && <span className="rec"><i></i>Best value</span>}
              <div className="tier">
                <i style={i === 1 ? { background: 'var(--pearl)' } : undefined}></i>
                {pack.name}
              </div>
              <div className="pline">
                <span className="amt">₹{fmt(pack.price)}</span>
                <span className="unit">one-time</span>
              </div>
              <p className="ptag">
                {fmt(pack.minutes)} connected minutes · ₹{pack.perMin.toFixed(2)}/min.
                {' '}{pack.tag}
              </p>
              <ul className="feats">
                <li><svg viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12" /></svg><span><b>{fmt(pack.minutes)} minutes</b> of live conversation</span></li>
                <li><svg viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12" /></svg><span>Unlimited agents &amp; campaign contacts</span></li>
                <li><svg viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12" /></svg><span>Transcripts with structured extraction</span></li>
                <li><svg viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12" /></svg><span>Live spend &amp; outcome dashboards</span></li>
                <li><svg viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12" /></svg><span>Credits never expire</span></li>
              </ul>
              <Link to="/login" className={`cta${i === 1 ? ' cta-solid' : ''}`}>
                Buy {pack.name}
              </Link>
            </div>
          ))}
        </div>

        <div className="est reveal" style={{ maxWidth: 580, margin: '44px auto 0', textAlign: 'left' }}>
          <span className="est-h">Estimate your monthly bill</span>
          <input
            type="range"
            min="100"
            max="5000"
            step="50"
            value={minutes}
            onChange={(e) => setMinutes(Number(e.target.value))}
            aria-label="Estimated connected minutes per month"
          />
          <div className="est-row">
            <span className="est-min"><b>{fmt(minutes)}</b> minutes / mo</span>
            <span className="est-cost"><span>₹{fmt(estimate.total)}</span> <small>/ month est.</small></span>
          </div>
          <div style={{ fontSize: 12, color: 'var(--dim)', marginTop: 10, lineHeight: 1.6 }}>
            {breakdown} — {fmt(estimate.covered)} minutes, effective ₹
            {effectiveRate.toFixed(2)}/min. Only connected calls consume credits;
            unanswered calls are free.
          </div>
        </div>

        <div className="note reveal">
          <span><svg viewBox="0 0 24 24"><rect x="3" y="11" width="18" height="11" rx="2" /><path d="M7 11V7a5 5 0 0 1 10 0v4" /></svg>No credit card for the free minutes</span>
          <span><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10" /><path d="M12 6v6l4 2" /></svg>Only connected calls are billed</span>
          <span><svg viewBox="0 0 24 24"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" /></svg>Playground time is always free</span>
        </div>

        <div className="mini-cta reveal">
          <h2>Start free. Top up when it works.</h2>
          <p>Create an agent, make your first calls on the 10 welcome minutes, and buy credits only when you take it live — ₹3.00 per minute, metered to the second, billed in rupees.</p>
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
            <Link to="/playground">Playground</Link>
            <Link to="/login">Sign in</Link>
            <a href="mailto:hello@echosarathi.ai">hello@echosarathi.ai</a>
          </div>
        </div>
      </footer>
    </div>
  );
}
