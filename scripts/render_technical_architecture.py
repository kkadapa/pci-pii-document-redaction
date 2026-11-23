"""
Renders the technical implementation diagram, with official Azure icons, to
docs/technical-architecture.svg.

Icons come from docs/icons/azure/ (Microsoft's Azure architecture icon set; see the README
there for terms) and are embedded as data URIs, so the SVG is self-contained and renders on
GitHub. Limits come from Microsoft documentation (checked November 2026); timings were
measured with this repo. See README.md and docs/architecture.md for sources.

Usage (from the project root):
  python scripts/render_technical_architecture.py
"""

import base64
import os
import textwrap
from xml.sax.saxutils import escape

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ICONS = os.path.join(ROOT, "docs", "icons", "azure")
OUT = os.path.join(ROOT, "docs", "technical-architecture.svg")

W, H = 1900, 1245
FONT = "Segoe UI, -apple-system, Helvetica Neue, Helvetica, Arial, sans-serif"

INK, MUTED, BORDER = "#1F2328", "#57606A", "#D0D7DE"
BLUE, TEAL, PURPLE, GREEN = "#0F6CBD", "#00796B", "#6B3FA0", "#1A7F37"
AMBER, NOTE = "#B7791F", "#8C959F"

parts = []
_icon_cache = {}


def add(s):
    parts.append(s)


def text(x, y, s, size=12, color=INK, weight="normal", anchor="start", style="normal"):
    add(f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}" font-weight="{weight}" '
        f'text-anchor="{anchor}" font-style="{style}">{escape(s)}</text>')


def icon(name, x, y, size=40):
    if name not in _icon_cache:
        with open(os.path.join(ICONS, f"{name}.svg"), "rb") as f:
            _icon_cache[name] = base64.b64encode(f.read()).decode("ascii")
    add(f'<image x="{x}" y="{y}" width="{size}" height="{size}" '
        f'href="data:image/svg+xml;base64,{_icon_cache[name]}"/>')


def badge(x, y, label, color):
    r = 13 if len(label) <= 2 else 16
    add(f'<circle cx="{x}" cy="{y}" r="{r}" fill="{color}" stroke="#FFFFFF" stroke-width="2.5"/>')
    text(x, y + 4.5, label, size=12 if len(label) <= 2 else 11, color="#FFFFFF", weight="bold", anchor="middle")


def bullets(x, y, width, lines):
    """Typed bullet lines: limit (amber), measured (green), note (grey). Returns end y."""
    chars = max(int((width - 18) / 6.3), 10)
    for kind, s in lines:
        color = {"limit": "#7A4E0B", "measured": "#116329", "note": INK}[kind]
        dot = {"limit": AMBER, "measured": GREEN, "note": NOTE}[kind]
        weight = "normal" if kind == "note" else "600"
        add(f'<rect x="{x}" y="{y - 8.5}" width="8" height="8" rx="{4 if kind == "note" else 1.5}" fill="{dot}"/>')
        for w in textwrap.wrap(s, chars):
            text(x + 14, y, w, size=12, color=color, weight=weight)
            y += 16
        y += 3
    return y


def card(x, y, w, h, step, title, lines, icon_name=None, color=BLUE, subtitle=None, in_repo=False):
    add(f'<g filter="url(#shadow)"><rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="#FFFFFF" stroke="{BORDER}"/></g>')
    add(f'<rect x="{x}" y="{y + 8}" width="4" height="{h - 16}" rx="2" fill="{color}"/>')
    tx = x + 16
    if icon_name:
        icon(icon_name, x + 14, y + 12, 36)
        tx = x + 60
    title_lines = textwrap.wrap(title, int((w - (tx - x) - 10) / 7.6))
    ty = y + 28 if len(title_lines) == 1 else y + 22
    for t in title_lines:
        text(tx, ty, t, size=14, weight="bold")
        ty += 17
    if subtitle:
        text(tx, ty, subtitle, size=11.5, color=MUTED, style="italic")
    if in_repo:
        add(f'<rect x="{x + w - 64}" y="{y - 9}" width="56" height="18" rx="9" fill="{PURPLE}"/>')
        text(x + w - 36, y + 4, "IN REPO", size=9.5, color="#FFFFFF", weight="bold", anchor="middle")
    bullets(x + 16, y + 68, w - 26, lines)
    if step:
        badge(x, y, step, color)


def arrow(points, dashed=False, color="#57606A"):
    d = "M" + " L".join(f"{px},{py}" for px, py in points)
    dash = ' stroke-dasharray="6 4"' if dashed else ""
    add(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="2"{dash} marker-end="url(#arrow)"/>')


def lane(x, y, w, h, label, color, fill):
    add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" fill="{fill}" stroke="{color}" '
        f'stroke-opacity="0.45" stroke-dasharray="6 4"/>')
    text(x + 14, y + 20, label, size=11.5, color=color, weight="bold")


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

text(30, 46, "Technical implementation on Azure: PCI/PII document redaction", size=24, weight="bold")
text(30, 72, "Which Azure service does what, from the first request to the masked JSON response. "
     "File bytes go straight to Blob Storage, never through API Management.", size=13, color=MUTED)

# Legend
lx, ly = 1340, 22
add(f'<rect x="{lx}" y="{ly}" width="530" height="62" rx="6" fill="#FFFFFF" stroke="{BORDER}"/>')
for (c, label, r), off in zip([(AMBER, "Service limit (Microsoft docs)", 1.5), (GREEN, "Measured in this repo", 1.5),
                               (NOTE, "Design note", 4)], [14, 220, 385]):
    add(f'<rect x="{lx + off}" y="{ly + 14}" width="9" height="9" rx="{r}" fill="{c}"/>')
    text(lx + off + 15, ly + 23, label, size=11.5)
add(f'<rect x="{lx + 14}" y="{ly + 36}" width="56" height="18" rx="9" fill="{PURPLE}"/>')
text(lx + 42, ly + 49, "IN REPO", size=9.5, color="#FFFFFF", weight="bold", anchor="middle")
text(lx + 78, ly + 49, "Logic exists in languageservice.py today; the rest is the target design", size=11.5)

# Client column -----------------------------------------------------------------------
cx, cy, cw, ch = 30, 110, 170, 880
add(f'<g filter="url(#shadow)"><rect x="{cx}" y="{cy}" width="{cw}" height="{ch}" rx="8" fill="#FFFFFF" stroke="{BORDER}"/></g>')
icon("users", cx + 65, cy + 14, 40)
text(cx + cw / 2, cy + 74, "Client app / user", size=14, weight="bold", anchor="middle")
for y, s, bold in [
    (cy + 100, "Bank portal, back-office", False), (cy + 115, "app, or batch uploader", False),
    (252, "A. POST /jobs", True), (268, "file name, size, type", False), (283, "(no file content)", False),
    (318, "B. GET /jobs/{id}", True), (334, "poll with Retry-After", False),
    (388, "← 202 job ID + upload URL", False), (404, "← 202 running, 200 / 422", False),
    (540, "C. PUT file to Blob", True), (556, "with the upload URL", False), (571, "(SAS, write-only)", False),
    (900, "D. Masked JSON back", True), (916, "~3 s for 1 page", False), (931, "34-40 s for 500 pages", False),
    (946, "~1.9 min for 2,000 pages", False),
]:
    text(cx + 12, y, s, size=12 if bold else 11.5, color=INK if bold else MUTED, weight="600" if bold else "normal")

# Lane A: request path -------------------------------------------------------------------
lane(215, 110, 1205, 300, "REQUEST PATH  ·  synchronous", BLUE, "#EEF5FC")
card(235, 160, 190, 160, "1", "Application Gateway + WAF", [
    ("note", "Public entry point, TLS"),
    ("note", "OWASP rules block common web attacks"),
], "application-gateway", BLUE)
card(450, 140, 390, 262, "2", "API Management", [
    ("note", "validate-azure-ad-token: Entra ID token, audience, scopes"),
    ("note", "rate-limit-by-key and quota-by-key per client"),
    ("limit", "Declared size ≤ 500 MB and allowed type: early reject only, the client could lie"),
    ("note", "Routes POST /jobs and GET /jobs/{id}"),
    ("note", "Calls Functions with its managed identity"),
    ("note", "Logs metadata only, never request bodies"),
], "api-management", BLUE, subtitle="Front door for every API call")
card(870, 140, 250, 125, "3", "Function: Create job", [
    ("note", "Job record, caller's oid as owner"),
    ("note", "SAS: write-only, 1 blob, short expiry"),
], "function-apps", BLUE)
card(870, 277, 250, 125, "12", "Function: Job status", [
    ("note", "Owner only (oid match), else 404"),
    ("note", "202 running, 200 JSON, 422 blocked"),
], "function-apps", BLUE)
card(1150, 175, 250, 180, "4", "Blob Storage: job store", [
    ("note", "One JSON blob per job: status, owner, timestamps"),
    ("note", "ETag checks stop lost updates"),
    ("note", "No document content, ever"),
], "storage-accounts", BLUE)
arrow([(200, 245), (231, 245)])
arrow([(425, 245), (446, 245)])
arrow([(840, 200), (866, 200)])
arrow([(840, 340), (866, 340)])
arrow([(1120, 200), (1135, 200), (1135, 240), (1146, 240)])
arrow([(1120, 340), (1135, 340), (1135, 300), (1146, 300)])
arrow([(450, 395), (204, 395)], dashed=True)

# Lane B: upload and intake ------------------------------------------------------------------
lane(215, 425, 1205, 248, "UPLOAD AND INTAKE  ·  event-driven", TEAL, "#ECF6F4")
card(235, 470, 215, 185, "5", "Blob Storage: quarantine", [
    ("note", "Client uploads directly with the SAS URL"),
    ("note", "Private container, encrypted at rest"),
    ("note", "Lifecycle rule deletes leftovers"),
], "storage-accounts", TEAL)
card(475, 470, 200, 185, "6", "Defender for Storage", [
    ("note", "Malware scan on upload"),
    ("note", "Result as blob index tag and Event Grid event"),
], "defender-for-cloud", TEAL)
card(700, 470, 190, 185, "7", "Event Grid topic", [
    ("note", "Delivers scan result to the Intake Function"),
    ("note", "Retries delivery"),
], "event-grid-topics", TEAL)
card(915, 460, 485, 200, "8", "Function: Intake validation (authoritative)", [
    ("note", "Malicious file: reject job, delete blob"),
    ("limit", "Size ≤ 500 MB, read from blob properties"),
    ("note", "Real type from first bytes, not the extension"),
    ("limit", "Pages ≤ 2,000, counted inside the file (PDF page list, TIFF frames)"),
    ("measured", "Page count: 500 pages 25 ms, 2,000 pages 99 ms"),
    ("note", "Pass: enqueue job. Fail: job rejected, blob deleted"),
], "function-apps", TEAL, in_repo=True)
arrow([(200, 560), (231, 560)])
arrow([(450, 562), (471, 562)])
arrow([(675, 562), (696, 562)])
arrow([(890, 562), (911, 562)])
arrow([(1275, 460), (1275, 344)], dashed=True)
text(1283, 420, "status", size=11, color=MUTED, style="italic")
arrow([(1150, 660), (1150, 678), (330, 678), (330, 736)])

# Lane C: processing ---------------------------------------------------------------------------
lane(215, 688, 1655, 302, "PROCESSING", PURPLE, "#F3EEFA")
card(235, 740, 190, 200, "9", "Service Bus queue", [
    ("note", "One message per job"),
    ("note", "Retries, then dead-letter queue"),
    ("note", "Worker scales on queue length"),
], "service-bus", PURPLE)
add(f'<rect x="450" y="712" width="1150" height="265" rx="10" fill="#FFFFFF" fill-opacity="0.55" stroke="{PURPLE}" stroke-opacity="0.6"/>')
icon("container-app", 462, 720, 26)
text(494, 738, "Container Apps: redaction worker (languageservice.py)  ·  fails closed: any error, no output", size=12.5, color=PURPLE, weight="bold")
badge(450, 712, "10", PURPLE)
card(470, 765, 265, 195, "10a", "Document Intelligence", [
    ("note", "prebuilt-read OCR"),
    ("limit", "S0: 15 analyze/s, 50 get/s"),
    ("limit", "Poll ≥ 2 s apart"),
    ("measured", "2,000 pages: 87.5 s (44 ms/page)"),
], "document-intelligence", TEAL, in_repo=True)
card(750, 765, 265, 195, "10b", "Chunker", [
    ("limit", "≤ 5,000 chars per chunk (API max 5,120)"),
    ("note", "100-character overlap"),
    ("measured", "2,000 pages: 2.4M chars, ~519 chunks"),
], None, PURPLE, in_repo=True)
card(1030, 765, 265, 195, "10c", "Azure AI Language: PII", [
    ("note", "API 2026-05-15-preview, explicit categories incl. CVV"),
    ("limit", "5 docs and 1 MB per request; S0: 300 req/min"),
    ("measured", "2,000 pages: ~104 requests in 26.5 s"),
], "language", TEAL, in_repo=True)
card(1310, 765, 270, 195, "10d", "Rules, mask, validate", [
    ("note", "Luhn card numbers, labeled CVV, expiry"),
    ("note", "Fail if a card number or CVV survives"),
    ("note", "Block mode: card data found, no text, 422"),
    ("measured", "500 pages: 0.11 s"),
], None, PURPLE, in_repo=True)
arrow([(425, 840), (446, 840)])
arrow([(735, 862), (746, 862)])
arrow([(1015, 862), (1026, 862)])
arrow([(1295, 862), (1306, 862)])
card(1625, 740, 230, 200, "11", "Blob Storage: results", [
    ("note", "Masked JSON only"),
    ("note", "Job status set to done"),
    ("note", "Raw file and extracted text deleted"),
], "storage-accounts", GREEN)
arrow([(1600, 862), (1621, 862)])

# Validation responsibility panel ----------------------------------------------------------------
px, py, pw, ph = 1440, 110, 430, 563
add(f'<g filter="url(#shadow)"><rect x="{px}" y="{py}" width="{pw}" height="{ph}" rx="8" fill="#FFFFFF" stroke="{BORDER}"/></g>')
add(f'<rect x="{px}" y="{py}" width="{pw}" height="40" rx="8" fill="{INK}"/>')
add(f'<rect x="{px}" y="{py + 30}" width="{pw}" height="10" fill="{INK}"/>')
text(px + 16, py + 26, "Where each check runs", size=15, color="#FFFFFF", weight="bold")
rows = [
    ("Caller identity (Entra ID token)", "API Management (2)", "Authoritative", BLUE),
    ("Rate limit and quota per client", "API Management (2)", "Authoritative", BLUE),
    ("Declared size ≤ 500 MB and file type", "API Management (2)", "Early reject only: the client declares it", AMBER),
    ("Malware", "Defender for Storage (6)", "Authoritative", TEAL),
    ("Actual size ≤ 500 MB", "Intake Function (8): blob properties", "Authoritative", TEAL),
    ("Real file type", "Intake Function (8): first bytes of the file", "Authoritative", TEAL),
    ("Pages ≤ 2,000", "Intake Function (8): counted inside the file", "Authoritative", TEAL),
    ("Anything the checks missed", "Document Intelligence (10a)", "Backstop: rejects files over its limits", PURPLE),
    ("Caller owns the job", "Job-status Function (12): oid in job record", "Authoritative: other callers get 404", BLUE),
]
ry = py + 66
for check, where, trust, color in rows:
    add(f'<rect x="{px + 14}" y="{ry - 12}" width="4" height="46" rx="2" fill="{color}"/>')
    text(px + 26, ry, check, size=12.5, weight="bold")
    text(px + 26, ry + 16, where, size=12, color=INK)
    text(px + 26, ry + 31, trust, size=11.5, color=MUTED, style="italic")
    ry += 52
text(px + 16, py + ph - 28, "API Management can't count pages: the file never reaches it,", size=11.5, color=MUTED)
text(px + 16, py + ph - 12, "and its content validation only inspects small bodies.", size=11.5, color=MUTED)

# Cross-cutting controls ------------------------------------------------------------------------
by = 1005
add(f'<rect x="30" y="{by}" width="1840" height="222" rx="10" fill="#FFFFFF" stroke="{BORDER}"/>')
text(46, by + 26, "CROSS-CUTTING CONTROLS  ·  every component above is in PCI DSS scope", size=11.5, color=MUTED, weight="bold")
chips = [
    ("entra-app-registrations", "Microsoft Entra ID", "Issues callers' tokens; API Management validates them. Key auth is disabled on the AI services"),
    ("managed-identities", "Managed identities", "API Management, Functions, and worker reach Storage, Service Bus, and AI services without keys"),
    ("key-vault", "Key Vault", "Only for secrets that can't use an identity, such as webhook signing keys"),
    ("private-endpoints", "Private endpoints", "Storage, Service Bus, Document Intelligence, Language, Key Vault"),
    ("virtual-networks", "Virtual network", "Functions and worker are VNet-integrated; public access is off on every backend"),
    ("application-insights", "Application Insights", "Request metadata, timings, and errors; never request bodies"),
    ("log-analytics", "Log Analytics", "Diagnostic logs from every resource; no document content or entity values"),
    ("defender-for-cloud", "Defender for Cloud", "Security posture and threat alerts across all resources"),
]
for i, (ic, title, desc) in enumerate(chips):
    col, row = i % 4, i // 4
    x, y = 46 + col * 456, by + 44 + row * 86
    add(f'<rect x="{x}" y="{y}" width="440" height="76" rx="8" fill="#F6F8FA" stroke="{BORDER}"/>')
    icon(ic, x + 12, y + 18, 38)
    text(x + 62, y + 26, title, size=13.5, weight="bold")
    for j, w in enumerate(textwrap.wrap(desc, 56)):
        text(x + 62, y + 44 + j * 15, w, size=11.5, color=MUTED)

add("</svg>")
with open(OUT, "w", encoding="utf-8") as f:
    f.write('<?xml version="1.0" encoding="UTF-8"?>\n' + "\n".join(parts))
print(f"Wrote {OUT}")
