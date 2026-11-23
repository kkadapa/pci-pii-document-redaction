"""
Renders the target-state architecture diagram to docs/architecture.svg.

Limits come from Microsoft documentation (checked November 2026). Timings were measured
with this repo on the synthetic 500- and 2,000-page statements. See README for sources.

Usage (from the project root):
  python scripts/render_architecture.py
"""

import os
import textwrap
from xml.sax.saxutils import escape

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "architecture.svg")

W, H = 1800, 983
FONT = "Segoe UI, -apple-system, Helvetica Neue, Helvetica, Arial, sans-serif"

# Colors
INK = "#1F2328"
MUTED = "#57606A"
BORDER = "#D0D7DE"
BLUE = "#0F6CBD"       # intake / API
TEAL = "#00796B"       # Azure AI services
PURPLE = "#6B3FA0"     # custom processing code
GREEN = "#1A7F37"      # delivery
AMBER = "#B7791F"      # service limits
MEASURED = "#1A7F37"   # measured numbers
NOTE = "#8C959F"       # design notes

COLS = [300, 600, 900, 1200, 1500]
CARD_W = 270

parts = []


def add(s):
    parts.append(s)


def text(x, y, s, size=12, color=INK, weight="normal", anchor="start", style="normal"):
    add(f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}" font-weight="{weight}" '
        f'text-anchor="{anchor}" font-style="{style}">{escape(s)}</text>')


def card(col, y, h, step, title, color, lines, in_repo=False):
    """A component card: colored header with step number, then typed bullet lines."""
    x = COLS[col]
    add(f'<g filter="url(#shadow)"><rect x="{x}" y="{y}" width="{CARD_W}" height="{h}" rx="8" fill="#FFFFFF" stroke="{BORDER}"/></g>')
    add(f'<path d="M{x},{y + 8} a8,8 0 0 1 8,-8 h{CARD_W - 16} a8,8 0 0 1 8,8 v30 h-{CARD_W} z" fill="{color}"/>')
    add(f'<circle cx="{x + 20}" cy="{y + 19}" r="11" fill="#FFFFFF"/>')
    text(x + 20, y + 23.5, str(step), size=12, color=color, weight="bold", anchor="middle")
    text(x + 38, y + 24, title, size=14, color="#FFFFFF", weight="bold")
    if in_repo:
        add(f'<rect x="{x + CARD_W - 62}" y="{y + 10}" width="52" height="18" rx="9" fill="#FFFFFF" fill-opacity="0.22" stroke="#FFFFFF" stroke-opacity="0.7"/>')
        text(x + CARD_W - 36, y + 23, "IN REPO", size=9.5, color="#FFFFFF", weight="bold", anchor="middle")

    cy = y + 58
    for kind, s in lines:
        if kind == "sub":
            for w in textwrap.wrap(s, 40):
                text(x + 14, cy, w, size=12, color=MUTED, style="italic")
                cy += 16
            cy += 3
            continue
        bullet = {"limit": AMBER, "measured": MEASURED, "note": NOTE}[kind]
        weight = "600" if kind != "note" else "normal"
        color = {"limit": "#7A4E0B", "measured": "#116329", "note": INK}[kind]
        wrapped = textwrap.wrap(s, 37)
        add(f'<rect x="{x + 14}" y="{cy - 8.5}" width="8" height="8" rx="{4 if kind == "note" else 1.5}" fill="{bullet}"/>')
        for w in wrapped:
            text(x + 28, cy, w, size=12, color=color, weight=weight)
            cy += 16
        cy += 2
    return x, y, h


def arrow(points, color="#57606A", dashed=False):
    d = "M" + " L".join(f"{px},{py}" for px, py in points)
    dash = ' stroke-dasharray="6 4"' if dashed else ""
    add(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="2"{dash} marker-end="url(#arrow)"/>')


def section_label(x, y, s):
    text(x, y, s, size=11.5, color=MUTED, weight="bold")


# ---------------------------------------------------------------------------------------
add(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" font-family="{FONT}">')
add("""<defs>
  <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
    <path d="M0,0 L10,5 L0,10 z" fill="#57606A"/>
  </marker>
  <filter id="shadow" x="-5%" y="-5%" width="110%" height="115%">
    <feDropShadow dx="0" dy="1.5" stdDeviation="2" flood-color="#1F2328" flood-opacity="0.10"/>
  </filter>
</defs>""")
add(f'<rect width="{W}" height="{H}" fill="#F6F8FA"/>')

# Title
text(30, 46, "Target-state architecture: PCI/PII document redaction on Azure", size=24, weight="bold")
text(30, 72, "Upload → OCR → PII/PCI detection → masking → JSON response. Limits from Microsoft docs (Nov 2026). "
     "Timings measured with this repo on 500- and 2,000-page text PDFs.", size=13, color=MUTED)

# Legend
lx, ly = 1290, 30
add(f'<rect x="{lx}" y="{ly}" width="480" height="58" rx="6" fill="#FFFFFF" stroke="{BORDER}"/>')
for (c, label, r), off in zip([(AMBER, "Service limit (Microsoft docs)", 1.5),
                               (MEASURED, "Measured in this repo", 1.5),
                               (NOTE, "Design note", 4)], [14, 215, 375]):
    bx = lx + off
    add(f'<rect x="{bx}" y="{ly + 14}" width="9" height="9" rx="{r}" fill="{c}"/>')
    text(bx + 15, ly + 23, label, size=11.5, color=INK)
add(f'<rect x="{lx + 14}" y="{ly + 33}" width="52" height="16" rx="8" fill="{PURPLE}"/>')
text(lx + 40, ly + 45, "IN REPO", size=9.5, color="#FFFFFF", weight="bold", anchor="middle")
text(lx + 74, ly + 45, "Implemented in languageservice.py today; other components are target state", size=11.5, color=INK)

# Client column ---------------------------------------------------------------------------
cx, cy0, cw, ch = 30, 140, 190, 695
add(f'<g filter="url(#shadow)"><rect x="{cx}" y="{cy0}" width="{cw}" height="{ch}" rx="8" fill="#FFFFFF" stroke="{BORDER}"/></g>')
add(f'<path d="M{cx},{cy0 + 8} a8,8 0 0 1 8,-8 h{cw - 16} a8,8 0 0 1 8,8 v30 h-{cw} z" fill="{INK}"/>')
text(cx + cw / 2, cy0 + 24, "Client / user", size=14, color="#FFFFFF", weight="bold", anchor="middle")
for i, s in enumerate(["Bank portal, back-office", "app, or batch uploader"]):
    text(cx + 12, cy0 + 58 + i * 16, s, size=12, color=MUTED, style="italic")
client_steps = [
    (232, "A. Create job (metadata)"),
    (282, "B. Get job ID + upload URL"),
    (318, "C. PUT file to Blob"),
    (420, "D. Wait: poll with"),
    (436, "    Retry-After, or webhook"),
    (700, "E. Receive masked JSON"),
    (722, "~2.5 min for 2,000 pages"),
    (738, "39-54 s for 500 pages"),
    (754, "~3 s for 1 page"),
]
for y, s in client_steps:
    text(cx + 12, y, s, size=12, color=INK if not s.startswith(("~", "    ")) else MUTED,
         weight="600" if s[:2] in ("A.", "B.", "C.", "D.", "E.") else "normal")

# Row 1: intake ----------------------------------------------------------------------------
R1, R1H = 140, 170
section_label(300, R1 - 12, "INTAKE  ·  API call returns in seconds; the file goes straight to Blob Storage")
card(0, R1, R1H, 1, "API Management", BLUE, [
    ("sub", "Single entry point, behind a WAF"),
    ("note", "Entra ID token, rate limits"),
    ("limit", "Declared size ≤ 500 MB (early check)"),
    ("note", "Returns 202 + job ID + upload URL"),
])
card(1, R1, R1H, 2, "Blob Storage (raw)", BLUE, [
    ("sub", "Quarantine container"),
    ("note", "Client uploads with a SAS URL"),
    ("note", "File bytes never pass APIM"),
    ("note", "Deleted after masking (step 12)"),
])
card(2, R1, R1H, 3, "Defender for Storage", BLUE, [
    ("sub", "Malware scan on upload"),
    ("note", "Result sent through Event Grid"),
    ("note", "Infected file: job rejected"),
])
card(3, R1, R1H, 4, "Intake Function", BLUE, [
    ("sub", "Authoritative checks"),
    ("limit", "≤ 500 MB: from blob properties"),
    ("limit", "≤ 2,000 pages: counted inside file"),
    ("note", "Real type from the file's first bytes"),
    ("measured", "Count: 500 pp 25 ms, 2,000 pp 99 ms"),
], in_repo=True)
card(4, R1, R1H, 5, "Service Bus queue", BLUE, [
    ("sub", "One message per job"),
    ("note", "Retries and dead-letter queue"),
    ("note", "Workers scale on queue depth"),
    ("note", "Decouples upload from processing"),
])
# client <-> APIM, client -> Blob
arrow([(220, 228), (296, 228)])
text(258, 220, "POST /jobs", size=10.5, color=MUTED, anchor="middle")
arrow([(300, 278), (224, 278)])
text(258, 296, "202 + URL", size=10.5, color=MUTED, anchor="middle")
arrow([(220, 326), (735, 326), (735, R1 + R1H + 4)], dashed=True)
text(470, 339, "PUT file with the SAS upload URL (bypasses API Management)", size=10.5, color=MUTED, anchor="middle")
for c in range(4):
    arrow([(COLS[c] + CARD_W, R1 + R1H / 2), (COLS[c + 1] - 4, R1 + R1H / 2)])

# Row 2: processing worker -------------------------------------------------------------------
R2C, R2, R2H = 345, 385, 190
add(f'<rect x="285" y="{R2C}" width="1500" height="255" rx="10" fill="#F3EEFA" stroke="{PURPLE}" stroke-opacity="0.45" stroke-dasharray="6 4"/>')
text(300, R2C + 24, "PROCESSING  ·  Redaction worker (Container Apps or Functions)  ·  fails closed: any error returns no output",
     size=11.5, color=PURPLE, weight="bold")
card(4, R2, R2H, 6, "Document Intelligence", TEAL, [
    ("sub", "prebuilt-read OCR"),
    ("limit", "S0: 15 analyze/s, 50 get/s (adjustable)"),
    ("limit", "Poll results ≥ 2 s apart"),
    ("note", "Large files: split with pages range"),
    ("measured", "2,000 pages in 108.8 s (54 ms/page)"),
], in_repo=True)
card(3, R2, R2H, 7, "Chunker", PURPLE, [
    ("sub", "Split text at line breaks"),
    ("limit", "≤ 5,000 chars per chunk (API max 5,120)"),
    ("note", "100-character overlap between chunks"),
    ("measured", "2,000 pages: 2.1M chars → 434 chunks"),
], in_repo=True)
card(2, R2, R2H, 8, "Azure AI Language PII", TEAL, [
    ("sub", "API 2026-05-15-preview, explicit categories incl. CVV, ExpirationDate"),
    ("limit", "5 docs per request, 1 MB per request"),
    ("limit", "S0: 100 req/s, 300 req/min"),
    ("note", "5 parallel requests, retry on 429"),
    ("measured", "2,000 pages: 87 requests in 36.7 s"),
], in_repo=True)
card(1, R2, R2H, 9, "Rule layer", PURPLE, [
    ("sub", "Deterministic backstop"),
    ("note", "Card numbers: 13-19 digits + Luhn"),
    ("note", "CVV and expiry after their labels"),
    ("measured", "0 extra hits: Language caught all 125 CVVs and expiry dates"),
], in_repo=True)
card(0, R2, R2H, 10, "Mask + validate", PURPLE, [
    ("sub", "Mask the union of all spans with *"),
    ("note", "Block if a card number or CVV survives"),
    ("note", "Any failed request: no output"),
    ("measured", "500 pp: rules + mask + check 0.09 s"),
], in_repo=True)
arrow([(1635, R1 + R1H), (1635, R2 - 4)])
for c in range(4, 0, -1):
    arrow([(COLS[c], R2 + R2H / 2), (COLS[c - 1] + CARD_W + 4, R2 + R2H / 2)])

# Row 3: delivery ------------------------------------------------------------------------------
R3, R3H = 655, 180
section_label(300, R3 - 12, "DELIVERY")
card(0, R3, R3H, 13, "Results API (via APIM)", BLUE, [
    ("sub", "GET /jobs/{id}"),
    ("note", "202 while running"),
    ("note", "200 + masked JSON when done"),
    ("note", "Or push via webhook (Event Grid)"),
])
card(1, R3, R3H, 11, "Result store", GREEN, [
    ("sub", "Masked JSON only"),
    ("note", "Entity metadata, no raw values"),
    ("note", "Audit: API and model versions"),
])
card(2, R3, R3H, 12, "Cleanup", GREEN, [
    ("sub", "Runs once the result is written"),
    ("note", "Delete raw file and extracted text"),
    ("note", "Logs: IDs, counts, timings only"),
])
# mask -> result store (elbow below the worker container)
arrow([(435, R2 + R2H), (435, 618), (735, 618), (735, R3 - 4)])
arrow([(870, R3 + R3H / 2), (896, R3 + R3H / 2)])
arrow([(600, R3 + R3H / 2), (574, R3 + R3H / 2)])
arrow([(300, 700), (224, 700)])
text(258, 690, "200 +", size=10.5, color=MUTED, anchor="middle")
text(258, 718, "JSON", size=10.5, color=MUTED, anchor="middle")

# Benchmark panel ---------------------------------------------------------------------------
px, py, pw, ph = 1200, R3, 585, R3H
add(f'<g filter="url(#shadow)"><rect x="{px}" y="{py}" width="{pw}" height="{ph}" rx="8" fill="#FFFFFF" stroke="{BORDER}"/></g>')
text(px + 16, py + 24, "Measured: synthetic bank statements (text PDFs)", size=13, weight="bold")
LIGHT, DARK = "#7FB8AE", TEAL
for i, (c, label) in enumerate([(LIGHT, "500 pages (861 KB)"), (DARK, "2,000 pages (3.4 MB)")]):
    lx2 = px + 16 + i * 150
    add(f'<rect x="{lx2}" y="{py + 34}" width="10" height="10" rx="2" fill="{c}"/>')
    text(lx2 + 15, py + 43, label, size=11, color=INK)
rows = [
    ("Document Intelligence", 28.9, 108.8),
    ("Language PII, 5 parallel", 10.2, 36.7),
    ("End to end", 39.2, 146.1),
]
scale = 330 / 146.1
for i, (label, small, large) in enumerate(rows):
    ry = py + 56 + i * 34
    text(px + 16, ry + 16, label, size=11.5, color=INK, weight="600" if label == "End to end" else "normal")
    for j, (secs, color) in enumerate([(small, LIGHT), (large, DARK)]):
        by = ry + j * 14
        add(f'<rect x="{px + 170}" y="{by}" width="{secs * scale:.1f}" height="11" rx="2" fill="{color}"/>')
        text(px + 170 + secs * scale + 6, by + 9.5, f"{secs} s", size=11, color=INK, weight="600")
text(px + 16, py + ph - 12, "Nov 22 2026. 500-page Document Intelligence time ranged 28.9-44.7 s over 2 runs. Scans not measured.",
     size=11, color=MUTED, style="italic")

# Cross-cutting controls ----------------------------------------------------------------------
by0 = 863
add(f'<rect x="30" y="{by0}" width="1755" height="95" rx="10" fill="#FFFFFF" stroke="{BORDER}"/>')
text(46, by0 + 26, "CROSS-CUTTING CONTROLS  ·  every component above is in PCI DSS scope", size=11.5, color=MUTED, weight="bold")
chips = [
    "Entra ID + managed identity (no keys in code)",
    "Key Vault for any remaining secrets",
    "Private endpoints, public network access off",
    "Azure Monitor: no document content in logs",
    "Regression test on every API / model change",
]
chip_x = 46
for s in chips:
    cw2 = 18 + len(s) * 6.55
    add(f'<rect x="{chip_x}" y="{by0 + 42}" width="{cw2:.0f}" height="32" rx="16" fill="#EEF2F6" stroke="{BORDER}"/>')
    text(chip_x + cw2 / 2, by0 + 62.5, s, size=12, color=INK, anchor="middle")
    chip_x += cw2 + 14

add("</svg>")

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", encoding="utf-8") as f:
    f.write('<?xml version="1.0" encoding="UTF-8"?>\n' + "\n".join(parts))
print(f"Wrote {OUT}")
