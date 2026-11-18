import React, { useEffect, useRef, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import ThemeToggle from './ThemeToggle.jsx';
import '../public-site.css';

export function PublicFaq({ id, items }) {
  return (
    <section className="es-public-section es-public-faq" aria-labelledby={id}>
      <div className="es-public-section-intro">
        <h2 id={id}>A few useful answers.</h2>
        <p>What to know before you open a workspace.</p>
      </div>
      <div className="es-public-questions">
        {items.map(({ question, answer }) => (
          <details key={question}>
            <summary>{question}</summary>
            <div className="es-public-answer">{answer}</div>
          </details>
        ))}
      </div>
    </section>
  );
}

export default function PublicLayout({ children }) {
  const { pathname, hash, key } = useLocation();
  const [mobileOpen, setMobileOpen] = useState(false);
  const toggleRef = useRef(null);
  const mobileNavRef = useRef(null);
  const brandRef = useRef(null);
  const landingPath = pathname === '/' || pathname === '/landing' ? pathname : '/landing';
  const links = [
    { to: `${landingPath}#product`, label: 'Product' },
    { to: `${landingPath}#usecases`, label: 'Use cases' },
    { to: '/pricing', label: 'Pricing' },
    { to: '/playground', label: 'Playground' },
    { to: '/roadmap', label: 'Roadmap' },
  ];

  useEffect(() => {
    setMobileOpen(false);
    if (hash) {
      const target = document.getElementById(hash.slice(1));
      if (target) {
        target.scrollIntoView({ behavior: 'auto', block: 'start' });
        target.focus({ preventScroll: true });
      }
    } else {
      window.scrollTo(0, 0);
    }
  }, [pathname, hash, key]);

  useEffect(() => {
    if (!mobileOpen) return undefined;
    const onKeyDown = (event) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        setMobileOpen(false);
        toggleRef.current?.focus();
      }
    };
    const desktop = window.matchMedia('(min-width: 1100px)');
    const onDesktop = (event) => {
      if (!event.matches) return;
      if (mobileNavRef.current?.contains(document.activeElement) || document.activeElement === toggleRef.current) {
        brandRef.current?.focus();
      }
      setMobileOpen(false);
    };
    document.addEventListener('keydown', onKeyDown);
    desktop.addEventListener('change', onDesktop);
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      desktop.removeEventListener('change', onDesktop);
    };
  }, [mobileOpen]);

  function closeAfterNavigation(event) {
    if (event.target.closest('a')) {
      setMobileOpen(false);
      toggleRef.current?.focus();
    }
  }

  function navigationLinks() {
    return links.map(({ to, label }) => (
      <Link key={label} to={to} aria-current={to === pathname ? 'page' : undefined}>
        {label}
      </Link>
    ));
  }

  return (
    <div className="es-public-site">
      <a className="es-public-skip" href="#es-public-main">Skip to content</a>
      <header className="es-public-header">
        <div className="es-public-container es-public-header-row">
          <Link className="es-public-brand" to="/landing" ref={brandRef} aria-label="Echo Sarathi home">
            <svg className="es-public-brand-mark" width="30" height="30" viewBox="0 0 32 32" fill="none" aria-hidden="true">
              <path d="M6 8h12a7 7 0 0 1 0 14h-3l-6 4v-6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
              <path d="M6 13h9M6 17h6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            </svg>
            <span>Echo Sarathi</span>
          </Link>
          <nav className="es-public-desktop-nav" aria-label="Main navigation">
            {navigationLinks()}
          </nav>
          <div className="es-public-header-actions">
            <ThemeToggle />
            <Link className="es-public-button es-public-header-cta" to="/login">Open workspace</Link>
            <button
              type="button"
              className="es-public-menu-toggle"
              ref={toggleRef}
              aria-expanded={mobileOpen}
              aria-controls="es-public-mobile-navigation"
              onClick={() => setMobileOpen((open) => !open)}
            >
              {mobileOpen ? 'Close' : 'Menu'}
              <svg width="18" height="18" viewBox="0 0 20 20" fill="none" aria-hidden="true">
                {mobileOpen
                  ? <path d="m5 5 10 10M15 5 5 15" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
                  : <path d="M3 6h14M3 10h14M3 14h14" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />}
              </svg>
            </button>
          </div>
        </div>
        <nav
          className="es-public-mobile-nav es-public-container"
          id="es-public-mobile-navigation"
          aria-label="Mobile navigation"
          hidden={!mobileOpen}
          ref={mobileNavRef}
          onClick={closeAfterNavigation}
        >
          {navigationLinks()}
          <Link to="/login" className="es-public-button">Open workspace</Link>
          <p>Existing account or invitation required.</p>
        </nav>
      </header>

      <main id="es-public-main" className="es-public-container" tabIndex={-1}>
        {children}
      </main>

      <footer className="es-public-footer">
        <div className="es-public-container es-public-footer-grid">
          <div className="es-public-footer-about">
            <Link className="es-public-brand" to="/landing">Echo Sarathi</Link>
            <p>Configure the conversation.<br />Keep the answers in view.</p>
            <small>© {new Date().getFullYear()} Echo Sarathi</small>
          </div>
          <nav aria-label="Product links">
            <h2>Product</h2>
            <Link to={`${landingPath}#workflow`}>How it works</Link>
            <Link to={`${landingPath}#usecases`}>Use cases</Link>
            <Link to="/pricing">Pricing</Link>
            <Link to="/roadmap">Roadmap</Link>
          </nav>
          <nav aria-label="Workspace links">
            <h2>Workspace</h2>
            <Link to="/">Overview</Link>
            <Link to="/agents">Agents</Link>
            <Link to="/agents/new">Agent builder</Link>
            <Link to="/campaigns">Campaigns</Link>
            <Link to="/calls">Call history</Link>
            <Link to="/playground">Playground</Link>
            <Link to="/credits">Billing &amp; credits</Link>
          </nav>
          <div className="es-public-footer-account">
            <h2>Account access</h2>
            <p>Already have access? Sign in to your workspace. For an invitation or account help, speak with your workspace administrator.</p>
            <Link className="es-public-text-link" to="/login">Sign in</Link>
          </div>
        </div>
      </footer>
    </div>
  );
}
