"""Draw Review-II deck diagrams (block diagram + flowchart) with Pillow."""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "review-2-assets"

BG = (10, 10, 11)
PANEL = (22, 22, 24)
LINE = (233, 228, 218)
MUTED = (168, 158, 140)
FG = (243, 239, 230)
ACCENT = (91, 169, 124)
GOLD = (201, 162, 39)


def _font(size: int):
    for candidate in (
        r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\segoeui.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _box(draw, xy, fill=PANEL, outline=LINE, width=2, radius=14):
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)


def _center(draw, cx, y, text, font, fill=FG):
    box = draw.textbbox((0, 0), text, font=font)
    draw.text((cx - (box[2] - box[0]) / 2, y), text, font=font, fill=fill)


def _arrow(draw, x1, y1, x2, y2, fill=LINE, width=3):
    draw.line((x1, y1, x2, y2), fill=fill, width=width)
    s = 10
    if x2 > x1:  # right
        draw.polygon([(x2, y2), (x2 - s, y2 - s // 2), (x2 - s, y2 + s // 2)], fill=fill)
    elif y2 > y1:  # down
        draw.polygon([(x2, y2), (x2 - s // 2, y2 - s), (x2 + s // 2, y2 - s)], fill=fill)


def block_diagram() -> Path:
    W, H = 1600, 1000
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    title, sub, body, small = _font(44), _font(26), _font(24), _font(20)
    _center(d, W // 2, 30, "EchoSarathi — System Block Diagram", title)
    _center(
        d, W // 2, 95,
        "INPUT (sensors)  →  CONTROLLER  →  OUTPUT (monitor)",
        sub, MUTED,
    )
    cols = [(60, 500, "INPUT", ACCENT,
             ["Caller's voice", "(PSTN, μ-law 8kHz)", "", "Contact card", "(campaign trigger)"]),
            (580, 1020, "CONTROLLER", LINE,
             ["LiveKit Room", "· Deepgram STT", "· Groq LLM + tools", "· Cartesia TTS", "",
              "Vobiz Bridge", "(WebSocket ↔ LiveKit)"]),
            (1100, 1540, "OUTPUT", GOLD,
             ["Agent's voice", "(μ-law 8kHz)", "", "Dashboard:", "· Transcript", "· Latency", "· Extracted fields"])]
    y0, y1 = 170, 660
    for x0, x1, label, color, lines in cols:
        _box(d, (x0, y0, x1, y1), outline=color, width=3)
        _center(d, (x0 + x1) // 2, y0 + 18, label, sub, color)
        y = y0 + 80
        for line in lines:
            if line == "":
                y += 12
                continue
            _center(d, (x0 + x1) // 2, y, line, body)
            y += 42
    _arrow(d, 500, 415, 580, 415)
    _arrow(d, 1020, 415, 1100, 415)
    _box(d, (580, 740, 1020, 930), outline=MUTED, width=2)
    _center(d, 800, 758, "DATA LAYER", sub, MUTED)
    for i, line in enumerate(["Postgres (calls, transcripts, fields)",
                              "Redis (session state, dialer queue)",
                              "Recordings (90-day retention)"]):
        _center(d, 800, 810 + i * 40, line, small, FG)
    _arrow(d, 800, 660, 800, 740)
    path = OUT / "block-diagram.png"
    img.save(path)
    return path


def flow_chart() -> Path:
    W, H = 1400, 1900
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    title, body, small = _font(44), _font(26), _font(21)
    _center(d, W // 2, 28, "EchoSarathi — Call Flow Chart", title)
    steps = [
        ("rect", "Campaign triggered (faculty launches)"),
        ("rect", "Load contact card + agent config"),
        ("rect", "Place call via Vobiz → PSTN"),
        ("diamond", "Parent answers?"),
        ("rect", "AI disclosure + verify parent"),
        ("rect", "Ask reason → extract field (tool)"),
        ("rect", "Ask return date → extract field (tool)"),
        ("rect", "Offer callback if asked"),
        ("rect", "end_call + summary → save transcript"),
        ("rect", "More queued? → next contact : Export CSV/XLSX"),
    ]
    cx, y, gap = W // 2, 120, 158
    bw, bh = 640, 84
    for i, (kind, text) in enumerate(steps):
        if kind == "diamond":
            pts = [(cx, y), (cx + 300, y + 62), (cx, y + 124), (cx - 300, y + 62)]
            d.polygon(pts, fill=PANEL, outline=GOLD, width=3)
            box = d.textbbox((0, 0), text, font=body)
            d.text((cx - (box[2] - box[0]) / 2, y + 62 - (box[3] - box[1]) / 2),
                   text, font=body, fill=FG)
            if i < len(steps) - 1:
                _arrow(d, cx, y + 124, cx, y + gap)
            # No-branch annotation
            d.text((cx + 320, y + 40), "No → log no_answer", font=small, fill=MUTED)
            y += gap + 20
        else:
            _box(d, (cx - bw // 2, y, cx + bw // 2, y + bh))
            box = d.textbbox((0, 0), text, font=body)
            d.text((cx - (box[2] - box[0]) / 2, y + (bh - (box[3] - box[1])) / 2),
                   text, font=body, fill=FG)
            if i < len(steps) - 1:
                _arrow(d, cx, y + bh, cx, y + gap)
            y += gap
    path = OUT / "flow-chart.png"
    img.save(path)
    return path


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    print(block_diagram())
    print(flow_chart())
    return 0


if __name__ == "__main__":
    sys.exit(main())
