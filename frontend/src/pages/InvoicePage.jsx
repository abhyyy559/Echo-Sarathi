import React, { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { billingApi } from '../api.js';
import '../account-pages.css';

/* One GST invoice. Everything on the sheet is frozen at issue time — the
 * billing profile can change later without rewriting history. */

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
  return d.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });
}

export default function InvoicePage() {
  const { id } = useParams();
  const [invoice, setInvoice] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let alive = true;
    setInvoice(null);
    setError(null);
    billingApi
      .invoice(id)
      .then((data) => {
        if (alive) setInvoice(data);
      })
      .catch((e) => {
        if (alive) setError(e.message || String(e));
      });
    return () => {
      alive = false;
    };
  }, [id]);

  if (error) {
    return (
      <div className="es-account es-account-invoice">
        <h2 className="page-title">Invoice unavailable</h2>
        <div className="banner banner-error" role="alert">
          {error}{' '}
          <Link to="/credits" className="btn btn-secondary btn-sm" style={{ marginLeft: 8 }}>
            Back to billing
          </Link>
        </div>
      </div>
    );
  }

  if (!invoice) {
    return (
      <div className="es-account es-account-invoice loading-page" role="status">
        <span className="spinner" /> Loading invoice…
      </div>
    );
  }

  const seller = invoice.seller || {};
  const rate = Number(invoice.gst_rate_percent || 18);

  return (
    <div className="invoice-page es-account es-account-invoice">
      <div className="invoice-print-bar">
        <div>
          <Link to="/credits" className="es-account-text-link">← Billing &amp; credits</Link>
          <h2 className="page-title">Invoice</h2>
          <p className="page-sub">Billing details as recorded when this invoice was issued.</p>
        </div>
        <button type="button" className="btn primary" onClick={() => window.print()}>
          Print / save as PDF
        </button>
      </div>

      <article className="invoice-sheet" aria-label={`Invoice ${invoice.number}`}>
        <header className="inv-head">
          <div>
            <div className="inv-label">Issued by</div>
            <div className="inv-seller">{seller.name || 'Seller name not provided'}</div>
            {seller.address && <div className="inv-muted inv-address">{seller.address}</div>}
            <div className="inv-muted">
              {seller.state ? `${seller.state} · ` : ''}
              {seller.gstin ? `GSTIN ${seller.gstin}` : 'GSTIN not configured'}
            </div>
          </div>
          <div className="inv-title">
            <div className="inv-tax">TAX INVOICE</div>
            <div className="inv-number mono">{invoice.number}</div>
            <div className="inv-muted">Issued {fmtDate(invoice.issued_at)}</div>
          </div>
        </header>

        <section className="inv-parties">
          <div>
            <div className="inv-label">Billed to</div>
            <div className="inv-strong">{invoice.customer_name || '—'}</div>
            {invoice.customer_email && (
              <div className="inv-muted">{invoice.customer_email}</div>
            )}
            {invoice.customer_address && (
              <div className="inv-muted inv-address">{invoice.customer_address}</div>
            )}
            {invoice.customer_state && (
              <div className="inv-muted">Place of supply: {invoice.customer_state}</div>
            )}
            {invoice.customer_gstin ? (
              <div className="inv-muted">GSTIN {invoice.customer_gstin}</div>
            ) : (
              <div className="inv-muted">Unregistered / B2C</div>
            )}
          </div>
          <div>
            <div className="inv-label">Payment</div>
            <div className="inv-muted">
              {invoice.payment_id ? `Reference #${invoice.payment_id}` : 'No payment reference'}
            </div>
            <div className="inv-muted">
              {invoice.subscription_id ? `Subscription #${invoice.subscription_id}` : 'One-time'}
            </div>
            <div className="inv-muted">Currency: INR</div>
          </div>
        </section>

        <table className="inv-table">
          <thead>
            <tr>
              <th>Description</th>
              <th className="num">Taxable value</th>
              <th className="num">GST {rate}%</th>
              <th className="num">Total</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>{invoice.description}</td>
              <td className="num">₹{inr(invoice.subtotal_paise / 100)}</td>
              <td className="num">₹{inr(invoice.gst_paise / 100)}</td>
              <td className="num">₹{inr(invoice.total_paise / 100)}</td>
            </tr>
          </tbody>
        </table>

        <div className="inv-totals">
          <div>
            <span>Taxable value</span>
            <span>₹{inr(invoice.subtotal_paise / 100)}</span>
          </div>
          <div>
            <span>GST @ {rate}% (CGST + SGST)</span>
            <span>₹{inr(invoice.gst_paise / 100)}</span>
          </div>
          <div className="inv-grand">
            <span>Total paid (incl. GST)</span>
            <span>₹{inr(invoice.total_paise / 100)}</span>
          </div>
        </div>

        <footer className="inv-foot">
          <p>Amounts are shown in INR. The taxable value and GST component are itemized above as recorded in the billing system.</p>
          <p>Keep invoice <b>{invoice.number}</b> and the payment reference for your records. Updating your billing profile applies to future invoices.</p>
        </footer>
      </article>
    </div>
  );
}
