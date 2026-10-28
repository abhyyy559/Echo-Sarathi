"""Transactional email over SMTP (no third-party SDK).

Delivery is best-effort: a missing SMTP configuration logs the message instead
of failing the business action that triggered it. Every public function takes
``Settings`` so tests can exercise the log-only path without touching a server.
"""
from __future__ import annotations

import logging
import smtplib
import threading
from email.message import EmailMessage
from typing import Optional

from app.config import Settings

logger = logging.getLogger(__name__)


def _rupees(paise: int) -> str:
    return f"Rs {paise / 100:,.2f}"


def _link(settings: Settings, path: str) -> str:
    return f"{(settings.frontend_base_url or '').rstrip('/')}/{path.lstrip('/')}"


def _html(title: str, body: str) -> str:
    return (
        "<div style=\"font-family:Inter,Arial,sans-serif;max-width:560px;margin:0 auto;"
        "color:#18202c\">"
        "<div style=\"padding:20px 0;border-bottom:1px solid #e6e9ef;font-weight:700;"
        "font-size:18px\">Echo Sarathi</div>"
        f"<h2 style=\"font-size:20px;margin:24px 0 8px\">{title}</h2>"
        f"<div style=\"font-size:14px;line-height:1.7\">{body}</div>"
        "<p style=\"margin-top:28px;font-size:12px;color:#7a8494\">"
        "Echo Sarathi Labs · AI voice calling for Indian teams</p>"
        "</div>"
    )


def send_email(
    settings: Settings,
    *,
    to: str,
    subject: str,
    text: str,
    html: Optional[str] = None,
) -> bool:
    """Send one message. Returns False when SMTP is off or delivery failed."""
    to = (to or "").strip()
    if not to:
        return False
    if not settings.smtp_host:
        logger.info(
            "email skipped (SMTP not configured): to=%s subject=%s\n%s",
            to,
            subject,
            text[:800],
        )
        return False
    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = to
    message["Subject"] = subject
    message.set_content(text)
    if html:
        message.add_alternative(html, subtype="html")
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
            if settings.smtp_tls:
                smtp.starttls()
            if settings.smtp_user:
                smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(message)
        logger.info("email sent: to=%s subject=%s", to, subject)
        return True
    except Exception:  # noqa: BLE001 — email must never break the request
        logger.warning("email delivery failed: to=%s subject=%s", to, subject, exc_info=True)
        return False


def send_email_async(
    settings: Settings,
    *,
    to: str,
    subject: str,
    text: str,
    html: Optional[str] = None,
) -> None:
    """Fire-and-forget delivery.

    Without SMTP configured the log-only path runs synchronously (cheap and
    deterministic in tests). With SMTP the message goes on a daemon thread so a
    slow mail server cannot delay a webhook or a call teardown.
    """
    kwargs = {"to": to, "subject": subject, "text": text, "html": html}
    if not settings.smtp_host:
        send_email(settings, **kwargs)
        return
    thread = threading.Thread(
        target=send_email,
        kwargs={"settings": settings, **kwargs},
        daemon=True,
        name="echo-email",
    )
    thread.start()


def welcome(settings: Settings, *, to: str, org_name: str, trial_minutes: int) -> None:
    login_url = _link(settings, "/login")
    text = (
        f"Welcome to Echo Sarathi, {org_name}.\n\n"
        f"Your organization has {trial_minutes} free minutes to try a real voice agent. "
        "Create an agent, test it in the browser playground, then launch a campaign.\n\n"
        f"Sign in: {login_url}\n\n"
        "Playground time is free. Only connected phone calls consume minutes."
    )
    send_email_async(
        settings,
        to=to,
        subject="Welcome to Echo Sarathi — your free minutes are ready",
        text=text,
        html=_html(
            f"Welcome, {org_name}",
            f"<p>Your account is ready with <b>{trial_minutes} free minutes</b>.</p>"
            "<p>Create an agent, test it in the playground, then launch your first "
            "campaign. Playground time is always free.</p>"
            f"<p><a href=\"{login_url}\" style=\"display:inline-block;background:#5b8cff;"
            "color:#fff;padding:10px 18px;border-radius:8px;text-decoration:none\">"
            "Open the console</a></p>",
        ),
    )


def receipt(
    settings: Settings,
    *,
    to: str,
    org_name: str,
    invoice_number: str,
    description: str,
    total_paise: int,
    invoice_id: int,
) -> None:
    invoice_url = _link(settings, f"/invoices/{invoice_id}")
    text = (
        f"Payment received for {org_name}.\n\n"
        f"{description}\nInvoice {invoice_number}\nTotal paid: {_rupees(total_paise)} "
        "(includes 18% GST)\n\n"
        f"View or print the invoice: {invoice_url}"
    )
    send_email_async(
        settings,
        to=to,
        subject=f"Receipt — {invoice_number} · {_rupees(total_paise)}",
        text=text,
        html=_html(
            "Payment received",
            f"<p><b>{description}</b></p>"
            f"<p>Invoice {invoice_number}<br/>Total paid: <b>{_rupees(total_paise)}</b> "
            "<span style=\"color:#7a8494\">(includes 18% GST)</span></p>"
            f"<p><a href=\"{invoice_url}\">View or print the invoice</a></p>",
        ),
    )


def low_balance(
    settings: Settings, *, to: str, org_name: str, balance_paise: int
) -> None:
    topup_url = _link(settings, "/credits")
    text = (
        f"{org_name}'s call wallet is down to {_rupees(balance_paise)}.\n\n"
        "Campaigns stop dialing when the wallet and any included plan minutes run out. "
        f"Top up to keep calling: {topup_url}"
    )
    send_email_async(
        settings,
        to=to,
        subject="Low call balance — campaigns may pause",
        text=text,
        html=_html(
            "Your call balance is running low",
            f"<p>The wallet is down to <b>{_rupees(balance_paise)}</b>.</p>"
            "<p>Campaigns pause automatically when payable minutes run out.</p>"
            f"<p><a href=\"{topup_url}\">Top up credits</a></p>",
        ),
    )


def plan_expiring(
    settings: Settings,
    *,
    to: str,
    org_name: str,
    plan_name: str,
    days_left: int,
    period_end: str,
) -> None:
    billing_url = _link(settings, "/credits")
    text = (
        f"{org_name}'s {plan_name} plan ends in {days_left} day(s), on {period_end}.\n\n"
        "Renew to keep included minutes and plan limits. After expiry the account "
        "falls back to the free plan and wallet overage.\n\n"
        f"Renew: {billing_url}"
    )
    send_email_async(
        settings,
        to=to,
        subject=f"{plan_name} plan ends in {days_left} day(s)",
        text=text,
        html=_html(
            f"{plan_name} plan ending soon",
            f"<p>Your plan ends on <b>{period_end}</b> ({days_left} day(s) left).</p>"
            "<p>Renew to keep included minutes and higher limits.</p>"
            f"<p><a href=\"{billing_url}\">Renew the plan</a></p>",
        ),
    )


def invite(
    settings: Settings,
    *,
    to: str,
    org_name: str,
    inviter_email: str,
    role: str,
    accept_url: str,
) -> None:
    text = (
        f"{inviter_email} invited you to {org_name} on Echo Sarathi as {role}.\n\n"
        f"Accept the invitation: {accept_url}\n\n"
        "The link expires in 7 days."
    )
    send_email_async(
        settings,
        to=to,
        subject=f"Invitation to {org_name} on Echo Sarathi",
        text=text,
        html=_html(
            f"Join {org_name}",
            f"<p><b>{inviter_email}</b> invited you as <b>{role}</b>.</p>"
            f"<p><a href=\"{accept_url}\" style=\"display:inline-block;background:#5b8cff;"
            "color:#fff;padding:10px 18px;border-radius:8px;text-decoration:none\">"
            "Accept invitation</a></p>"
            "<p style=\"font-size:12px;color:#7a8494\">This link expires in 7 days.</p>",
        ),
    )


def password_reset(settings: Settings, *, to: str, reset_url: str) -> None:
    text = (
        "Reset your Echo Sarathi password.\n\n"
        f"{reset_url}\n\n"
        "The link expires in 30 minutes. If you did not request this, ignore this email."
    )
    send_email_async(
        settings,
        to=to,
        subject="Reset your Echo Sarathi password",
        text=text,
        html=_html(
            "Reset your password",
            f"<p><a href=\"{reset_url}\">Choose a new password</a></p>"
            "<p style=\"font-size:12px;color:#7a8494\">This link expires in 30 minutes. "
            "If you did not request it, you can ignore this email.</p>",
        ),
    )
