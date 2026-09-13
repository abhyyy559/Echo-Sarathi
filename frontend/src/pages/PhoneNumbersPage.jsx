import React from 'react';
import { Link } from 'react-router-dom';

/** Phone Numbers — placeholder surface (DID provisioning arrives later). */
export default function PhoneNumbersPage() {
  return (
    <div className="narrow">
      <div className="page-head">
        <div>
          <h2 className="page-title">Phone numbers</h2>
          <p className="page-sub">Provision Indian DIDs and manage caller-ID settings.</p>
        </div>
      </div>
      <div className="card placeholder-hero">
        <div className="placeholder-glow">
          <svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2z" />
          </svg>
        </div>
        <h2 className="placeholder-title">Phone numbers are coming soon</h2>
        <p className="placeholder-sub">
          You will provision Indian DIDs, attach them to campaigns and manage caller-ID and DLT header settings from
          here. For now, sandbox calling works entirely through the Playground and Test Call.
        </p>
        <div className="empty-action">
          <Link to="/guide" className="btn btn-primary btn-sm">
            See what ships today
          </Link>
        </div>
      </div>
    </div>
  );
}
