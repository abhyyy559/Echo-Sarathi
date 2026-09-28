"""Assemble the Review-II deck PDF from content + diagrams + screenshots."""
from __future__ import annotations

import sys
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (Image, PageBreak, Paragraph, Spacer, Table,
                                TableStyle)

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "docs" / "review-2-assets"
OUT = ROOT / "docs" / "EchoSarathi_Review-II.pdf"

BG = colors.HexColor("#0A0A0B")
PANEL = colors.HexColor("#161618")
CREAM = colors.HexColor("#F3EFE6")
MUTED = colors.HexColor("#A89E8C")
BRAND = colors.HexColor("#E9E4DA")
GREEN = colors.HexColor("#5BA97C")

PAGE_W, PAGE_H = A4
MARGIN = 18 * mm
CONTENT_W = PAGE_W - 2 * MARGIN

styles = getSampleStyleSheet()
sTitle = ParagraphStyle("Title2", parent=styles["Title"], fontSize=26,
                        leading=30, textColor=CREAM, alignment=1, spaceAfter=4 * mm)
sH1 = ParagraphStyle("H1", parent=styles["Heading1"], fontSize=20, leading=24,
                     textColor=BRAND, spaceBefore=2 * mm, spaceAfter=3 * mm)
sH2 = ParagraphStyle("H2", parent=styles["Heading2"], fontSize=13, leading=16,
                     textColor=CREAM, spaceBefore=3 * mm, spaceAfter=2 * mm)
sBody = ParagraphStyle("Body2", parent=styles["BodyText"], fontSize=10.5,
                       leading=15, textColor=CREAM, spaceAfter=2 * mm)
sSmall = ParagraphStyle("Small", parent=sBody, fontSize=9, leading=12.5, textColor=MUTED)
sCenter = ParagraphStyle("Center", parent=sBody, alignment=1)

SLIDE = {"fontSize": 11, "leading": 14, "textColor": MUTED, "alignment": 2}


def _bg(canvas, _doc):
    canvas.saveState()
    canvas.setFillColor(BG)
    canvas.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    canvas.restoreState()


def _footer(canvas, doc):
    _bg(canvas, doc)
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(MUTED)
    canvas.drawRightString(PAGE_W - MARGIN, 12 * mm, f"Slide {doc.page}")
    canvas.drawString(MARGIN, 12 * mm, "EchoSarathi — Voice AI for Bharat · Review-II")
    canvas.restoreState()


def slide_no(n: int, title: str):
    return [Paragraph(f"<font color='#A89E8C' size=9>SLIDE {n}</font>", sSmall),
            Paragraph(title, sH1)]


def _rs(text: str) -> str:
    """Helvetica has no rupee glyph (renders as a box) — use Rs. instead."""
    return text.replace("₹", "Rs. ")


def bullets(items: list[str]):
    return [Paragraph(f"•&nbsp;&nbsp;{_rs(t)}", sBody) for t in items]


def table(headers: list[str], rows: list[list[str]], widths=None):
    data = [[Paragraph(f"<b>{_rs(h)}</b>", sSmall) for h in headers]]
    for row in rows:
        data.append([Paragraph(_rs(c), sSmall) for c in row])
    style = TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), PANEL),
        ("TEXTCOLOR", (0, 0), (-1, -1), CREAM),
        ("GRID", (0, 0), (-1, -1), 0.5, MUTED),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ])
    return Table(data, colWidths=widths, style=style)


def img(name: str, max_w=CONTENT_W, max_h=150 * mm):
    from PIL import Image as PILImage
    p = ASSETS / name
    with PILImage.open(p) as im:
        w, h = im.size
    scale = min(max_w / w, max_h / h)
    return Image(str(p), width=w * scale, height=h * scale)


def build() -> Path:
    from reportlab.platypus import SimpleDocTemplate
    story: list = []

    # 1 — Title
    story += [Spacer(1, 45 * mm),
              Paragraph("EchoSarathi — Voice AI for Bharat", sTitle),
              Paragraph("A self-serve voice agent platform for Indian SMBs", sCenter),
              Spacer(1, 8 * mm),
              Paragraph("Social Innovation and Entrepreneurship (A500507) · Review-II", sCenter),
              Paragraph("[College Name] · [Semester, Academic Year]", sCenter),
              Spacer(1, 8 * mm),
              Paragraph("Team: [Name 1 — Roll No.], [Name 2 — Roll No.], "
                        "[Name 3 — Roll No.], [Name 4 — Roll No.]", sCenter),
              Paragraph("Faculty Mentor: [Mentor Name, Designation]", sCenter),
              PageBreak()]
    # 2 — Outline
    story += slide_no(2, "Presentation Outline") + bullets([
        "Problem Statement", "Existing Solutions", "Gaps in Existing Solutions",
        "Proposed Solution", "Components Required", "Block Diagram", "Flow Chart",
        "Working Principle of Components", "Working of the Model",
        "Results and Conclusions", "References"]) + [PageBreak()]
    # 3 — Problem
    story += slide_no(3, "Problem Statement — 60M Indian SMBs, no affordable voice calling") + bullets([
        "<b>Manual and expensive:</b> schools call parents one by one; clinics remind patients by hand; shops confirm orders over phone. Staff time lost — or the calls never happen.",
        "<b>Enterprise voice AI is unaffordable:</b> Ringg/Gnani/Uniphore charge ₹6+/min with enterprise contracts. A school in Warangal cannot buy that.",
        "<b>SMB tools are black boxes:</b> no transcript, no latency, no audit of why a call failed. Owners cannot improve what they cannot see."]) + [PageBreak()]
    # 4 — Existing
    story += slide_no(4, "Existing Solutions") + bullets([
        "<b>Ringg AI</b> — enterprise voice agents (Practo, Flipkart); $15.5M funding; ₹6/min. SMBs excluded by contracts.",
        "<b>Outpero</b> — SMB voice agent, ₹4,999/mo + ₹3.5/min, 10+ languages. Black box: no stack visibility.",
        "<b>ThinnestAI</b> — ₹1.5–2/min + passthrough. Cheapest, but developer-only: no templates, no dashboard.",
        "<b>Human BPO agents</b> — ₹25–40/min, 60–80% attrition. Expensive, inconsistent, unscalable."]) + [PageBreak()]
    # 5 — Gaps
    story += slide_no(5, "Gaps in Existing Solutions")
    story += [table(["Gap", "Who has it", "What's missing"], [
        ["SMB affordability", "Ringg, Gnani, Uniphore", "Enterprise pricing blocks 60M+ SMBs"],
        ["Vertical templates", "ThinnestAI, Vapi, Retell", "Require code; no pre-built agents"],
        ["Observability", "All SMB platforms", "No per-turn latency / field audit"],
        ["Vertical depth", "Vacademy (edu-only)", "Locked to one vertical"],
        ["Code-switching depth", "Most others", "Coverage ≠ depth; mid-sentence Telugu-English rare"],
        ["Data sovereignty", "Global platforms", "Voice data leaves India; DPDP risk"],
    ], widths=[38 * mm, 42 * mm, 94 * mm])]
    story += [Paragraph("No platform combines <b>SMB pricing + vertical templates + observability + data sovereignty</b>.", sBody), PageBreak()]
    # 6 — Proposed
    story += slide_no(6, "Proposed Solution — EchoSarathi") + bullets([
        "Sign up → pick a template (attendance, appointment, fee, COD) → fill contact card → test in browser playground → launch campaign."])
    story += [table(["Feature", "EchoSarathi", "Outpero", "ThinnestAI", "Ringg"], [
        ["Self-serve", "Yes", "Yes", "Yes", "No"],
        ["Vertical templates", "Yes", "Partial", "No", "Enterprise"],
        ["Per-turn latency visible", "Yes", "No", "No", "No"],
        ["Extracted fields audit", "Yes", "No", "No", "No"],
        ["Data sovereignty", "Self-hosted", "No", "No", "No"],
        ["Price per minute", "Rs 2.99", "Rs 3.50", "Rs 2.14", "Rs 6.00"],
    ], widths=[42 * mm, 30 * mm, 30 * mm, 30 * mm, 30 * mm])]
    story += [Paragraph("Pricing: ₹4,999/mo (500 min included) + ₹2.99/min overage.", sBody), PageBreak()]
    # 7 — Components
    story += slide_no(7, "Components Required")
    story += [Paragraph("Hardware", sH2), table(["Item", "Purpose"], [
        ["Cloud VM (4 vCPU, 8GB)", "Hosts LiveKit, backend, voice worker"],
        ["Smartphone + Indian SIM", "End-to-end test calls to +91 numbers"],
        ["USB headset / mic", "Browser playground testing"],
        ["Developer laptop", "Development, testing, deployment"],
    ], widths=[55 * mm, 119 * mm]), Paragraph("Software", sH2),
        table(["Layer", "Technology", "Purpose"], [
        ["Orchestration", "LiveKit (self-hosted)", "Rooms, agent lifecycle, audio routing"],
        ["Telephony", "Vobiz", "India PSTN, mu-law 8kHz WebSocket"],
        ["STT", "Deepgram Nova-2 Phonecall", "Streaming ASR, telephony-tuned"],
        ["LLM", "Groq Llama 3.1 8B Instant", "Responses + tool calling, <200ms TTFT"],
        ["TTS", "Cartesia Sonic / Sarvam Bulbul V3", "Streaming speech, 8kHz out"],
        ["Backend", "Python FastAPI", "Calls, campaigns, webhooks"],
        ["Frontend", "React", "Dashboard, Call Detail, playground"],
        ["Database", "SQLite / Postgres", "Calls, transcripts, fields"],
        ["Cache", "Redis", "Session state, dialer queue"],
        ["Deploy", "Docker Compose", "Containers"],
    ], widths=[30 * mm, 55 * mm, 89 * mm]), PageBreak()]
    # 8 — Block diagram
    story += slide_no(8, "Block Diagram") + [img("block-diagram.png"), PageBreak()]
    # 9 — Flow chart
    story += slide_no(9, "Flow Chart") + [img("flow-chart.png", max_h=215 * mm), PageBreak()]
    # 10 — Working principle
    story += slide_no(10, "Working Principle of All Components") + bullets([
        "<b>Vobiz:</b> dumb pipe — PSTN audio (mu-law 8kHz) to WebSocket and back.",
        "<b>LiveKit:</b> one room per call; routes audio bridge ↔ worker; turn-taking + barge-in.",
        "<b>Deepgram:</b> interim + final transcripts; endpointing 300ms.",
        "<b>Groq LLM:</b> replies + tool calls (record fields, end call); 300-token cap.",
        "<b>Cartesia:</b> streams first audio in ~150ms, sentence by sentence.",
        "<b>Backend/Frontend/Data:</b> FastAPI control + React dashboard; Postgres records, Redis queue, 90-day recordings."]) + [PageBreak()]
    # 11 — Model pictures 1
    story += slide_no(11, "Project Model — Agents & Campaign") + [
        img("02-agents.png", max_h=85 * mm),
        Paragraph("Agent workspace — persona, versions, voice settings.", sSmall),
        img("03-campaign-contacts.png", max_h=85 * mm),
        Paragraph("Campaign roster — contacts with Skip/Include selection.", sSmall),
        PageBreak()]
    # 12 — Model pictures 2
    story += slide_no(12, "Project Model — Playground & Call Detail") + [
        img("04-playground.png", max_h=85 * mm),
        Paragraph("Browser playground — test any agent version, zero minutes.", sSmall),
        img("05-call-detail.png", max_h=85 * mm),
        Paragraph("Call Detail — transcript, extracted fields with confidence.", sSmall),
        PageBreak()]
    # 13 — Results
    story += slide_no(13, "Results")
    story += [table(["Metric", "Result"], [
        ["Real outbound calls", "Working to +91 numbers via Vobiz"],
        ["TTS first audio", "117ms"],
        ["Greeting", "~35 words / under 10s"],
        ["Cost per 50s call", "Rs 0.80"],
        ["Agent templates", "2: attendance follow-up, appointment reminder"],
        ["Contact card flow", "Verified end-to-end"],
        ["Tests", "Backend 213/213 · voice-agent 110/110"],
    ], widths=[50 * mm, 124 * mm])]
    story += [Paragraph("Ongoing: turn-detection tuning, greeting pre-render, interruption handling, latency-consistent model.", sBody), PageBreak()]
    # 14 — Conclusions
    story += slide_no(14, "Conclusions") + bullets([
        "Voice AI for Indian SMBs is viable at ₹2.99/min with 55–66% margin.",
        "The gap (SMB pricing + templates + observability + sovereignty) is real and fillable.",
        "Observability — per-turn latency, fields, outcomes in one view — is the differentiator.",
        "Self-hosted data path answers DPDP objections from hospitals/NBFCs.",
        "Code-switching (Sarvam, Phase 2) opens Tier-2/3 India.",
        "Hard engineering done; remaining: self-serve layer, DLT, billing."]) + [PageBreak()]
    # 15 — References
    story += slide_no(15, "References") + bullets([
        "IEEE Access 2023 — voice UI design for Indian languages (IEEE Xplore).",
        "IEEE/ACM TASLP 2024 — end-to-end ASR for low-resource Indian languages.",
        "IEEE TNNLS 2024 — LLMs for conversational AI survey.",
        "ICASSP 2025 — latency optimization in cascaded STT-LLM-TTS pipelines.",
        "Industry: ringg.ai · outpero.com · thinnest.ai · vobiz.ai · docs.livekit.io/agents · sarvam.ai · DPDP Act (meity.gov.in).",
        "<i>Verify exact titles/years on IEEE Xplore before submission.</i>"]) + [PageBreak()]
    # 16 — Thank you
    story += [Spacer(1, 90 * mm), Paragraph("THANK YOU", sTitle),
              Paragraph("EchoSarathi — Voice AI for Bharat", sCenter), PageBreak()]
    # 17 — Questions
    story += [Spacer(1, 90 * mm), Paragraph("Questions?", sTitle),
              Paragraph("Contact: [team email] | [project repo link]", sCenter)]

    doc = SimpleDocTemplate(str(OUT), pagesize=A4, leftMargin=MARGIN,
                            rightMargin=MARGIN, topMargin=16 * mm, bottomMargin=16 * mm,
                            title="EchoSarathi — Review-II", author="EchoSarathi team")
    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return OUT


if __name__ == "__main__":
    print(build())
    sys.exit(0)
