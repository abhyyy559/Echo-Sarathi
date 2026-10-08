import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import '../od-pricing.css';

/* Pricing — ported from frontend by opendesign/pricing.html.
 * Public page: no auth, no backend calls. Estimator is local state.
 */
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

  // Billed in rupees: ₹8.50/min (≈ $0.10 × 85). Indian digit grouping.
  const cost = (minutes * 8.5).toLocaleString('en-IN', { maximumFractionDigits: 0 });

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
        <span className="kick reveal">Pricing</span>
        <h1 className="reveal">Two ways to start.<br />Both simple.</h1>
        <p className="sub reveal">Explore on us. Scale by the second. No seats, no platform fee, no surprise line items — your live spend always sits on your dashboard.</p>

        <div className="grid">
          <div className="pcard reveal">
            <div className="tier"><i></i>Free</div>
            <div className="pline"><span className="amt">₹0</span><span className="unit">forever</span></div>
            <p className="ptag">One agent, real conversations, real structured data. Everything you need to hear the difference before spending anything.</p>
            <ul className="feats">
              <li><svg viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12" /></svg><span><b>1 voice agent</b> with full builder access</span></li>
              <li><svg viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12" /></svg><span><b>30 call minutes</b> every month</span></li>
              <li><svg viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12" /></svg><span>Complete Playground testing</span></li>
              <li><svg viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12" /></svg><span>Transcripts with confidence scores</span></li>
              <li><svg viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12" /></svg><span>Community support</span></li>
            </ul>
            <Link to="/login" className="cta">Start free</Link>
          </div>

          <div className="pcard featured reveal" style={{ transitionDelay: '.12s' }}>
            <span className="rec"><i></i>Recommended</span>
            <div className="tier"><i style={{ background: 'var(--pearl)' }}></i>Pay as you go</div>
            <div className="pline"><span className="amt">₹8.50</span><span className="unit">per minute · billed by the second</span></div>
            <p className="ptag">Unlimited agents and campaigns. Metered to the second — watch spend tick live while your campaigns run.</p>
            <div className="est">
              <span className="est-h">Estimate your month</span>
              <input type="range" min="100" max="5000" step="50" value={minutes} onChange={(e) => setMinutes(Number(e.target.value))} aria-label="Estimated minutes per month" />
              <div className="est-row">
                <span className="est-min"><b>{minutes.toLocaleString('en-IN')}</b> minutes / mo</span>
                <span className="est-cost"><span>₹{cost}</span> <small>/ month est.</small></span>
              </div>
            </div>
            <ul className="feats">
              <li><svg viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12" /></svg><span><b>Unlimited agents</b> &amp; immutable versions</span></li>
              <li><svg viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12" /></svg><span><b>Parallel campaign calling</b> to thousands of contacts</span></li>
              <li><svg viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12" /></svg><span>Natural turn-taking &amp; instant barge-in</span></li>
              <li><svg viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12" /></svg><span>Live spend, latency &amp; outcome dashboards</span></li>
              <li><svg viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12" /></svg><span>CSV / Excel export of every captured field</span></li>
              <li><svg viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12" /></svg><span>Priority support</span></li>
            </ul>
            <Link to="/login" className="cta cta-solid">Create your agent</Link>
          </div>
        </div>

        <div className="note reveal">
          <span><svg viewBox="0 0 24 24"><rect x="3" y="11" width="18" height="11" rx="2" /><path d="M7 11V7a5 5 0 0 1 10 0v4" /></svg>No credit card for the free tier</span>
          <span><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10" /><path d="M12 6v6l4 2" /></svg>Only connected calls are billed</span>
          <span><svg viewBox="0 0 24 24"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" /></svg>Playground time is always free</span>
        </div>

        <div className="mini-cta reveal">
          <h2>Start free. Scale when it works.</h2>
          <p>Create an agent, run your first calls on us, and only pay when you take it live — ₹8.50 per minute, metered to the second, billed in rupees.</p>
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
