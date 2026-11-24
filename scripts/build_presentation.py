"""
Builds the team walkthrough deck: docs/presentation/pci-pii-redaction-walkthrough.pptx,
and a PDF copy for viewing on GitHub.

Every number on the slides comes from the README's test results and the transcripts in
docs/evidence/logs/. Diagrams and screenshots are taken from docs/.

Requirements: python-pptx, headless Google Chrome (to render the SVG diagrams as PNG),
and LibreOffice (for the PDF copy; skipped if not installed).

Usage (from the project root):
  python scripts/build_presentation.py
"""

import os
import shutil
import subprocess
import tempfile

from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")
EVIDENCE = os.path.join(DOCS, "evidence")
OUT_DIR = os.path.join(DOCS, "presentation")
OUT_PPTX = os.path.join(OUT_DIR, "pci-pii-redaction-walkthrough.pptx")
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
SOFFICE_CANDIDATES = ["/Applications/LibreOffice.app/Contents/MacOS/soffice", "soffice", "libreoffice"]
REPO_URL = "github.com/kkadapa/pci-pii-document-redaction"

FONT = "Arial"
NAVY = RGBColor(0x0B, 0x25, 0x45)
BLUE = RGBColor(0x00, 0x78, 0xD4)
TEXT = RGBColor(0x24, 0x29, 0x2F)
MUTED = RGBColor(0x5F, 0x6B, 0x7A)
LIGHT = RGBColor(0xF3, 0xF6, 0xFA)
LINE = RGBColor(0xD0, 0xD7, 0xDE)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
GREEN = RGBColor(0x10, 0x7C, 0x10)
GREEN_BG = RGBColor(0xE8, 0xF5, 0xE9)
AMBER = RGBColor(0x9A, 0x5B, 0x00)
AMBER_BG = RGBColor(0xFF, 0xF4, 0xDB)
RED = RGBColor(0xB4, 0x23, 0x18)
RED_BG = RGBColor(0xFD, 0xEC, 0xEA)
BLUE_BG = RGBColor(0xE6, 0xF2, 0xFB)

SLIDE_W, SLIDE_H = 13.333, 7.5
MARGIN = 0.6


# ---------------------------------------------------------------- helpers

def _run(paragraph, text, size, bold=False, color=TEXT, italic=False):
    run = paragraph.add_run()
    run.text = text
    run.font.name = FONT
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.italic = italic
    run.font.color.rgb = color
    return run


def _rich(paragraph, text, size, color=TEXT, bold=False):
    """Adds text where **double-starred** parts are bold."""
    parts = text.split("**")
    for i, part in enumerate(parts):
        if part:
            _run(paragraph, part, size, bold=bold or i % 2 == 1, color=color)


def textbox(slide, x, y, w, h, lines, size=16, color=TEXT, align=PP_ALIGN.LEFT,
            anchor=MSO_ANCHOR.TOP, bold=False, spacing=6):
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = box.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = Inches(0.05)
    tf.margin_top = tf.margin_bottom = Inches(0.03)
    for i, line in enumerate([lines] if isinstance(lines, str) else lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.space_after = Pt(spacing)
        _rich(p, line, size, color=color, bold=bold)
    return box


def bullets(slide, x, y, w, h, items, size=16, color=TEXT, spacing=8):
    """items: strings, or (string, level) tuples. **bold** markup supported."""
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = box.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = Inches(0.05)
    for i, item in enumerate(items):
        text, level = (item, 0) if isinstance(item, str) else item
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.space_after = Pt(spacing)
        marker = "•  " if level == 0 else "–  "
        _run(p, ("      " * level) + marker, size - 2 * level, color=BLUE if level == 0 else MUTED)
        _rich(p, text, size - 2 * level, color=color)
    return box


def panel(slide, x, y, w, h, fill=LIGHT, border=None, shape=MSO_SHAPE.ROUNDED_RECTANGLE):
    s = slide.shapes.add_shape(shape, Inches(x), Inches(y), Inches(w), Inches(h))
    s.fill.solid()
    s.fill.fore_color.rgb = fill
    if border is None:
        s.line.fill.background()
    else:
        s.line.color.rgb = border
        s.line.width = Pt(1)
    s.shadow.inherit = False
    if shape == MSO_SHAPE.ROUNDED_RECTANGLE:
        s.adjustments[0] = 0.08
    return s


def callout(slide, x, y, w, h, title, body, fill=BLUE_BG, accent=BLUE, size=14):
    panel(slide, x, y, w, h, fill=fill)
    bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y + 0.12), Inches(0.07), Inches(h - 0.24))
    bar.fill.solid()
    bar.fill.fore_color.rgb = accent
    bar.line.fill.background()
    # Estimate how many lines the title wraps to (average glyph width ~0.55 em) so the body starts below it
    chars_per_line = max(1, int((w - 0.4) / (0.55 * (size + 1) / 72)))
    title_lines = -(-len(title) // chars_per_line)
    title_h = 0.3 * title_lines + 0.1
    textbox(slide, x + 0.2, y + 0.1, w - 0.35, title_h, title, size=size + 1, bold=True, color=accent)
    body_lines = [body] if isinstance(body, str) else body
    textbox(slide, x + 0.2, y + 0.2 + title_h, w - 0.35, h - title_h - 0.3, body_lines, size=size, spacing=4)


def stat(slide, x, y, w, h, value, label, color=BLUE, fill=LIGHT):
    panel(slide, x, y, w, h, fill=fill)
    textbox(slide, x + 0.15, y + 0.12, w - 0.3, 0.8, value, size=30, bold=True, color=color, align=PP_ALIGN.CENTER)
    textbox(slide, x + 0.15, y + 0.92, w - 0.3, h - 1.0, label, size=13, color=TEXT, align=PP_ALIGN.CENTER)


def table(slide, x, y, w, rows, col_widths, size=12, row_h=0.36, header_fill=NAVY, highlight=None):
    """rows[0] is the header. highlight: {(row, col): (fg, bg)} for individual cells."""
    highlight = highlight or {}
    shape = slide.shapes.add_table(len(rows), len(rows[0]), Inches(x), Inches(y),
                                   Inches(w), Inches(row_h * len(rows)))
    tbl = shape.table
    total = sum(col_widths)
    for c, cw in enumerate(col_widths):
        tbl.columns[c].width = Inches(w * cw / total)
    for r, row in enumerate(rows):
        tbl.rows[r].height = Inches(row_h)
        for c, value in enumerate(row):
            cell = tbl.cell(r, c)
            cell.margin_left = cell.margin_right = Inches(0.08)
            cell.margin_top = cell.margin_bottom = Inches(0.04)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            fg, bg = highlight.get((r, c), (None, None))
            cell.fill.solid()
            if r == 0:
                cell.fill.fore_color.rgb = header_fill
            else:
                cell.fill.fore_color.rgb = bg or (WHITE if r % 2 else LIGHT)
            tf = cell.text_frame
            tf.word_wrap = True
            p = tf.paragraphs[0]
            _rich(p, str(value), size, color=WHITE if r == 0 else (fg or TEXT), bold=(r == 0))
    return tbl


def picture(slide, path, x, y, max_w, max_h, border=False):
    """Places an image inside the box, keeping its aspect ratio, centered horizontally."""
    iw, ih = Image.open(path).size
    scale = min(max_w / iw, max_h / ih)
    w, h = iw * scale, ih * scale
    left = x + (max_w - w) / 2
    pic = slide.shapes.add_picture(path, Inches(left), Inches(y), Inches(w), Inches(h))
    if border:
        pic.line.color.rgb = LINE
        pic.line.width = Pt(0.75)
    return pic


def arrow(slide, x, y, w=0.28, h=0.3, color=MUTED):
    a = slide.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW, Inches(x), Inches(y), Inches(w), Inches(h))
    a.fill.solid()
    a.fill.fore_color.rgb = color
    a.line.fill.background()


class Deck:
    def __init__(self):
        self.prs = Presentation()
        self.prs.slide_width = Inches(SLIDE_W)
        self.prs.slide_height = Inches(SLIDE_H)
        self.blank = self.prs.slide_layouts[6]
        self.count = 0

    def slide(self, title, kicker=None, notes=None):
        self.count += 1
        s = self.prs.slides.add_slide(self.blank)
        bar = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, Inches(0.18), Inches(SLIDE_H))
        bar.fill.solid()
        bar.fill.fore_color.rgb = BLUE
        bar.line.fill.background()
        if kicker:
            textbox(s, MARGIN, 0.3, 10, 0.35, kicker.upper(), size=12, bold=True, color=BLUE)
        textbox(s, MARGIN, 0.58, SLIDE_W - 2 * MARGIN, 0.7, title, size=28, bold=True, color=NAVY)
        textbox(s, MARGIN, SLIDE_H - 0.42, 8, 0.3, "PCI/PII document redaction on Azure  ·  Team walkthrough",
                size=10, color=MUTED)
        textbox(s, SLIDE_W - MARGIN - 1, SLIDE_H - 0.42, 1, 0.3, str(self.count), size=10, color=MUTED,
                align=PP_ALIGN.RIGHT)
        if notes:
            s.notes_slide.notes_text_frame.text = notes
        return s

    def section(self, number, title, subtitle, notes=None):
        self.count += 1
        s = self.prs.slides.add_slide(self.blank)
        bg = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, Inches(SLIDE_W), Inches(SLIDE_H))
        bg.fill.solid()
        bg.fill.fore_color.rgb = NAVY
        bg.line.fill.background()
        textbox(s, 1.0, 2.3, 11, 0.6, f"PART {number}", size=16, bold=True, color=RGBColor(0x6C, 0xB8, 0xF6))
        textbox(s, 1.0, 2.85, 11, 1.0, title, size=40, bold=True, color=WHITE)
        textbox(s, 1.0, 3.95, 11, 1.0, subtitle, size=18, color=RGBColor(0xC9, 0xD6, 0xE3))
        if notes:
            s.notes_slide.notes_text_frame.text = notes
        return s


def render_svg(svg_path, png_path, scale=2):
    """Renders an SVG to PNG with headless Chrome (python-pptx can't embed SVG)."""
    with open(svg_path, encoding="utf-8") as f:
        head = f.read(400)
    w = int(head.split('width="')[1].split('"')[0])
    h = int(head.split('height="')[1].split('"')[0])
    with tempfile.TemporaryDirectory() as tmp:
        page = os.path.join(tmp, "page.html")
        with open(page, "w", encoding="utf-8") as f:
            f.write(f'<!doctype html><html><body style="margin:0;background:#fff">'
                    f'<img src="file://{svg_path}" width="{w}" height="{h}" style="display:block"></body></html>')
        subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                        f"--force-device-scale-factor={scale}", f"--window-size={w},{h}",
                        "--allow-file-access-from-files", f"--screenshot={png_path}", f"file://{page}"],
                       capture_output=True, check=True)
    return png_path


# ---------------------------------------------------------------- slides

def build(tmp):
    d = Deck()
    logical_png = render_svg(os.path.join(DOCS, "architecture.svg"), os.path.join(tmp, "architecture.png"))
    technical_png = render_svg(os.path.join(DOCS, "technical-architecture.svg"),
                               os.path.join(tmp, "technical-architecture.png"))

    # 1. Title -------------------------------------------------------------
    d.count += 1
    s = d.prs.slides.add_slide(d.blank)
    bg = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, Inches(SLIDE_W), Inches(SLIDE_H))
    bg.fill.solid()
    bg.fill.fore_color.rgb = NAVY
    bg.line.fill.background()
    stripe = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(1.0), Inches(2.05), Inches(1.2), Inches(0.08))
    stripe.fill.solid()
    stripe.fill.fore_color.rgb = BLUE
    stripe.line.fill.background()
    textbox(s, 1.0, 2.3, 11.3, 1.6, "PCI/PII document redaction on Azure", size=44, bold=True, color=WHITE)
    textbox(s, 1.0, 3.45, 11.3, 1.0,
            "What we built, what we measured, and what we learned",
            size=22, color=RGBColor(0xC9, 0xD6, 0xE3))
    textbox(s, 1.0, 4.6, 11.3, 1.2, [
        "Azure AI Document Intelligence  +  Azure AI Language PII detection",
        f"Team walkthrough  ·  November 2026  ·  {REPO_URL}",
    ], size=15, color=RGBColor(0x9F, 0xB3, 0xC8))
    s.notes_slide.notes_text_frame.text = (
        "Purpose of this session: walk through the PCI/PII redaction prototype from start to finish. "
        "What problem it solves, how the pipeline works, what we tested and measured, what broke, the target-state "
        "architecture, and an honest view of what it would take to run this in production. "
        "Everything on these slides is in the GitHub repo, with the evidence behind each number.")

    # 2. Agenda --------------------------------------------------------------
    s = d.slide("Agenda", notes="Five parts. Parts 2 and 3 carry most of the evidence; part 5 is the discussion.")
    parts = [
        ("1", "The problem and the result", "What we set out to do, and the outcome in one slide"),
        ("2", "The pipeline, and how we got here", "The 8 steps, the timeline, and what broke along the way"),
        ("3", "Test results", "Realistic 500- and 2,000-page batches: accuracy, over-masking, processing time"),
        ("4", "Service limits, tested live", "9 limits deliberately exceeded, with screenshots. One silent failure found"),
        ("5", "Target architecture and next steps", "Azure design, decisions, honest assessment, known gaps, recommendations"),
    ]
    for i, (n, title, sub) in enumerate(parts):
        y = 1.55 + i * 1.02
        c = s.shapes.add_shape(MSO_SHAPE.OVAL, Inches(MARGIN), Inches(y), Inches(0.62), Inches(0.62))
        c.fill.solid()
        c.fill.fore_color.rgb = BLUE
        c.line.fill.background()
        c.text_frame.text = ""
        _run(c.text_frame.paragraphs[0], n, 20, bold=True, color=WHITE)
        c.text_frame.paragraphs[0].alignment = PP_ALIGN.CENTER
        textbox(s, MARGIN + 0.85, y - 0.02, 11, 0.4, title, size=20, bold=True, color=NAVY)
        textbox(s, MARGIN + 0.85, y + 0.38, 11, 0.4, sub, size=14, color=MUTED)

    # ---------------------------------------------------------------- PART 1
    d.section(1, "The problem and the result", "Upload a document, get JSON back with every card and personal value masked")

    s = d.slide("The problem", kicker="Why this exists", notes=(
        "Banks and card issuers receive documents like dispute forms and payment authorizations that contain full "
        "card numbers and CVVs. PCI DSS forbids storing CVVs after authorization, and any system that holds full card "
        "numbers is in PCI scope. The goal was a service that removes this data automatically, at the scale of real "
        "statement batches, and never returns a partly masked result."))
    bullets(s, MARGIN, 1.55, 6.6, 5, [
        "Financial documents (statements, card dispute forms, payment authorizations) carry **card numbers, CVVs, "
        "expiry dates, SSNs, names, emails, phone numbers**",
        "PCI DSS forbids storing **CVVs** after authorization, and any system holding full card numbers is in "
        "**PCI scope**",
        "Batches are large: hundreds to thousands of pages, scanned or digital",
        "Downstream teams still need the rest of the document",
    ], size=17)
    callout(s, 7.6, 1.55, 5.1, 2.35, "Goal", [
        "Upload a document  →  receive **JSON with every sensitive value masked**.",
        "Original values are never returned or logged.",
    ], size=15)
    callout(s, 7.6, 4.1, 5.1, 2.55, "Scope of this exercise", [
        "Working prototype on two Azure services",
        "Realistic tests at **500 and 2,000 pages**",
        "Every service limit **tested live**, with screenshots",
        "Target-state Azure architecture",
    ], fill=LIGHT, accent=NAVY, size=15)

    s = d.slide("The result in one slide", kicker="Summary", notes=(
        "Headline: on the realistic batches, no card data leaked, at 500 or at 2,000 pages. 2,000 pages is the Document "
        "Intelligence maximum and took about 1.9 minutes end to end. We deliberately exceeded 9 limits against the live "
        "services. The most important finding is that Document Intelligence does not reject a file over 2,000 pages; "
        "it silently analyzes only the first 2,000 and reports success. The pipeline now guards against that. "
        "The weak spot is person names in capitals. This is a prototype, not production."))
    stat(s, MARGIN, 1.55, 2.9, 1.65, "0", "card numbers, CVVs, or expiry dates leaked (102 forms, 500 + 2,000 pages)", GREEN, GREEN_BG)
    stat(s, MARGIN + 3.07, 1.55, 2.9, 1.65, "1.9 min", "end to end for 2,000 pages, the Document Intelligence maximum", BLUE)
    stat(s, MARGIN + 6.14, 1.55, 2.9, 1.65, "9", "service limits deliberately exceeded against the live services", BLUE)
    stat(s, MARGIN + 9.21, 1.55, 2.9, 1.65, "1", "silent failure found: files over 2,000 pages truncated with no error", AMBER, AMBER_BG)
    bullets(s, MARGIN, 3.55, 12.1, 3.2, [
        "**What works:** Document Intelligence extracts the text; Azure AI Language (preview API) finds card data, SSNs, "
        "emails, and phones; a rule layer and a final check make the pipeline **fail closed**",
        "**Weak spot:** about **15% of customer names printed in capitals** were not masked. A personal-data gap, "
        "not a card-data gap",
        "**Trade-off:** heavy over-masking. Transaction reference numbers are masked as phone numbers",
        "**Dependency:** CVV and expiry detection use Language API **preview** features",
        "**Status:** prototype. The pipeline code runs; the Azure target architecture is designed but not deployed",
    ], size=16)

    # ---------------------------------------------------------------- PART 2
    d.section(2, "The pipeline, and how we got here",
              "Two Azure services, a rule layer, and a fail-closed check")

    s = d.slide("The pipeline: 8 steps", kicker="languageservice.py", notes=(
        "Step 0 runs before any Azure call: size, the real file type from the first bytes, and the page count from inside "
        "the file. Document Intelligence extracts text. We chunk to 5,000 characters because Language accepts at most "
        "5,120 per document, ending chunks at line breaks with 100 characters of overlap so a card number is never cut "
        "in half. Language runs with an explicit category list on the preview API, 5 chunks per request, 5 requests in "
        "parallel. The rule layer is deterministic: Luhn-valid card numbers and labeled CVVs and expiry dates. We mask "
        "the union of everything found, then validate: if any card number or CVV survives, the whole job fails. "
        "Finally the PCI policy: mask, or block the document outright."))
    steps = [
        ("0", "Pre-check", "Size ≤ 500 MB, real type, pages ≤ 2,000", NAVY),
        ("1", "Document Intelligence", "prebuilt-read extracts the text", BLUE),
        ("2", "Chunk", "≤ 5,000 chars, line breaks, 100-char overlap", NAVY),
        ("3", "Language PII", "Preview API, explicit categories incl. CVV", BLUE),
        ("4", "Rules", "Luhn card numbers, labeled CVV and expiry", NAVY),
        ("5", "Mask", "Union of all detected spans", NAVY),
        ("6", "Validate", "Any card number or CVV left → fail", RED),
        ("7", "PCI policy", "mask (200) or block (422)", GREEN),
    ]
    bw, gap, y0 = 1.31, 0.23, 1.75
    for i, (n, name, desc, color) in enumerate(steps):
        x = MARGIN + i * (bw + gap)
        panel(s, x, y0, bw, 2.25, fill=LIGHT, border=LINE)
        top = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y0), Inches(bw), Inches(0.12))
        top.fill.solid()
        top.fill.fore_color.rgb = color
        top.line.fill.background()
        textbox(s, x + 0.08, y0 + 0.2, bw - 0.16, 0.4, n, size=22, bold=True, color=color)
        textbox(s, x + 0.08, y0 + 0.65, bw - 0.16, 0.55, name, size=13, bold=True, color=NAVY)
        textbox(s, x + 0.08, y0 + 1.2, bw - 0.16, 1.0, desc, size=11, color=TEXT)
        if i < len(steps) - 1:
            arrow(s, x + bw - 0.01, y0 + 0.95, w=gap + 0.02, h=0.26)
    callout(s, MARGIN, 4.35, 5.95, 2.3, "Fail closed", [
        "Any Language error, any chunk error, a page-count mismatch, or a surviving card number or CVV returns "
        "**status: error and no text**.",
        "Error messages never contain document content.",
    ], fill=RED_BG, accent=RED, size=13)
    callout(s, MARGIN + 6.15, 4.35, 5.95, 2.3, "Why the REST API, not the SDK", [
        "The Language SDK (5.4.0) stops at API **2023-04-01**, which has no CVV category.",
        "The current GA API (**2026-05-01**) also missed the CVV in our test. Only **2026-05-15-preview** with "
        "explicit categories masked it.",
    ], size=13)

    s = d.slide("How we got here", kicker="The journey, step by step", notes=(
        "This is the order things happened in. Each step was driven by a test result or a design review question. "
        "Notice that the biggest changes came from testing: the CVV gap, the silent truncation, the network failures. "
        "And the architecture changed twice after review: Cosmos DB was replaced by Blob Storage, and Container Apps by "
        "Functions."))
    timeline = [
        ("Build", "Two-service pipeline working end to end. First bug: a 401 because the Document Intelligence key was "
                  "used against the Language endpoint"),
        ("Harden", "CVVs weren't masked → preview REST API with explicit categories, rule layer, output check, fail closed"),
        ("Scale test", "Synthetic 500-page statement batch; enterprise guidance and limits documented"),
        ("Architect", "Target-state architecture: async jobs, queue, worker, time budgets"),
        ("Pre-check", "Size and page-count checks before any Azure call, tested at 2,000 and 2,001 pages"),
        ("2,000 pages", "Full run at the Document Intelligence maximum: about 1.9 minutes"),
        ("Azure design", "Technical diagram with official Azure icons; which checks run in API Management vs Functions"),
        ("Design review", "Cosmos DB → Blob Storage; jobs bound to their owner; PCI block mode"),
        ("Evidence", "Realistic batches; 9 limits exceeded live → found silent truncation → fail-closed page check"),
        ("Simplify", "Worker moved from Container Apps to Functions: one compute service"),
    ]
    col_w = 5.95
    for i, (tag, text) in enumerate(timeline):
        col, row = divmod(i, 5)
        x = MARGIN + col * (col_w + 0.2)
        y = 1.5 + row * 1.05
        c = s.shapes.add_shape(MSO_SHAPE.OVAL, Inches(x), Inches(y + 0.05), Inches(0.45), Inches(0.45))
        c.fill.solid()
        c.fill.fore_color.rgb = AMBER if tag == "Evidence" else BLUE
        c.line.fill.background()
        c.text_frame.word_wrap = False
        c.text_frame.margin_left = c.text_frame.margin_right = 0
        _run(c.text_frame.paragraphs[0], str(i + 1), 13, bold=True, color=WHITE)
        c.text_frame.paragraphs[0].alignment = PP_ALIGN.CENTER
        textbox(s, x + 0.6, y - 0.02, col_w - 0.6, 0.35, tag, size=14, bold=True, color=NAVY)
        textbox(s, x + 0.6, y + 0.3, col_w - 0.6, 0.7, text, size=12, color=TEXT)

    s = d.slide("What broke along the way, and what we changed", kicker="Lessons learned", notes=(
        "Worth spending time on. Several of these would have been production incidents. The 000- SSN and the scorer "
        "issues are test-quality lessons: bad test data produced false alarms, and a naive scorer produced false leaks. "
        "The TLS failures were on the test machine's network path, not the services, but the retries are needed anyway. "
        "The silent truncation is the most serious finding of the project."))
    table(s, MARGIN, 1.45, 12.1, [
        ["What we saw", "Cause", "What we changed"],
        ["401 from the Language service", "Document Intelligence key and endpoint used for Language",
         "Two resources, separate endpoint and key settings"],
        ["CVVs and expiry dates not masked", "SDK limited to API 2023-04-01; GA API 2026-05-01 doesn't detect CVVs",
         "REST call to **2026-05-15-preview** with explicit categories, plus rules"],
        ["SSNs reported as leaked", "Early test data used 000- SSNs, which are never issued, so not recognized",
         "Use published example SSNs. Test data must look real"],
        ["Scorer reported false leaks", "Substring matching of 3-digit CVVs anywhere in the text",
         "Label-anchored scoring: read the value after each form label"],
        ["Runs failed at random", "**17–23%** of new TLS connections from the test machine failed the handshake",
         "Retries: 10 for Document Intelligence, 8 with backoff and jitter for Language"],
        ["2,001-page file reported “succeeded”", "Document Intelligence **silently analyzes only 2,000 pages**",
         "Pre-check, plus fail closed if fewer pages come back than the file has"],
        ["Size test gave a false result", "Test harness bugs: conflicting upload headers; a dropped connection "
         "counted as a rejection", "Real Content-Length upload; verdict only after bytes are sent"],
    ], [2.6, 4.3, 4.3], size=12, row_h=0.62,
        highlight={(6, 1): (RED, None)})

    # ---------------------------------------------------------------- PART 3
    d.section(3, "Test results", "Realistic synthetic statement batches at 500 and 2,000 pages")

    s = d.slide("Test documents: realistic statement batches", kicker="scripts/generate_banking_pdf.py", notes=(
        "We didn't want a test file with a card number on every page. Real statement batches mostly contain already-masked "
        "references like 'card ending in 4444'. Full card data appears only on occasional forms. So the generator "
        "builds statements with summary, transaction, fee, and disclosure pages, and attaches a form to about one "
        "statement in five, at irregular positions. All values are fictional: public test card numbers and published "
        "example SSNs. A ground-truth file lists every planted value so we can score the output."))
    picture(s, os.path.join(EVIDENCE, "00-test-document-sample-pages.png"), MARGIN, 1.4, 12.1, 2.55, border=True)
    table(s, MARGIN, 4.15, 12.1, [
        ["", "500-page batch", "2,000-page batch"],
        ["File size / statements", "752 KB / 84 statements", "3.0 MB / 330 statements"],
        ["Pages with full card data", "26 forms (5.2% of pages), 6–38 pages apart",
         "76 forms (3.8% of pages), 6–135 pages apart"],
        ["Extracted text", "598,991 characters (~1,198 per page)", "2,437,253 characters (~1,219 per page)"],
        ["Each form contains", "Name, email, phone, SSN, full card number, expiry, CVV",
         "Same, on 76 forms"],
    ], [2.6, 4.75, 4.75], size=12, row_h=0.45)
    textbox(s, MARGIN, 6.5, 12.1, 0.4,
            "All data is fictional: public test card numbers, made-up names, published example SSNs. "
            "Ground truth lists every planted value.", size=11, color=MUTED)

    s = d.slide("Detection accuracy", kicker="scripts/score_results.py", notes=(
        "Every card number, CVV, and expiry date on all 102 forms was masked, at both sizes. The rule layer found nothing "
        "extra, so the Language service caught it all; the rules are a backstop. SSNs, emails, and phones were also all "
        "masked. Names are the weak spot: 15% of names printed in capitals on summary pages, and one mixed-case name on a "
        "form at 2,000 pages. Block mode doesn't help with that, because names aren't card data."))
    green = (GREEN, GREEN_BG)
    amber = (AMBER, AMBER_BG)
    table(s, MARGIN, 1.45, 7.3, [
        ["Value on the forms", "Leaked, 500 pp", "Leaked, 2,000 pp"],
        ["Card number", "0 / 26", "0 / 76"],
        ["CVV", "0 / 26", "0 / 76"],
        ["Expiry date", "0 / 26", "0 / 76"],
        ["SSN", "0 / 26", "0 / 76"],
        ["Email", "0 / 26", "0 / 76"],
        ["Phone", "0 / 26", "0 / 76"],
        ["Cardholder name", "0 / 26", "**1 / 76**"],
        ["Name in capitals, summary pages", "**13 / 84 (15%)**", "**51 / 330 (15%)**"],
    ], [3.3, 2, 2], size=13, row_h=0.47,
        highlight={**{(r, c): green for r in range(1, 7) for c in (1, 2)},
                   (7, 1): green, (7, 2): amber, (8, 1): amber, (8, 2): amber})
    callout(s, 8.2, 1.45, 4.5, 2.25, "All card data masked", [
        "102 of 102 forms: card number, CVV, and expiry masked.",
        "Rule layer found **0 extra** (rule_only_detections = 0). It's a backstop.",
    ], fill=GREEN_BG, accent=GREEN, size=13)
    callout(s, 8.2, 3.9, 4.5, 2.75, "Names are the weak spot", [
        "~15% of names in capitals not recognized, e.g. on statement summary pages.",
        "A personal-data gap, not card data. Block mode doesn't help.",
        "“Card ending in 4444” stays readable, which is correct under PCI masking rules.",
    ], fill=AMBER_BG, accent=AMBER, size=13)

    s = d.slide("Over-masking: safe, but costly for the business", kicker="All entities returned", notes=(
        "The flip side of high recall. On 2,000 pages Language returned 32,433 entities for 76 forms' worth of planted "
        "values. Most are transaction reference numbers detected as phone numbers and merchant locations detected as "
        "addresses. That is safe for PCI, but operations teams lose information they need. Fixing it means filtering "
        "by context, or dropping categories you don't need."))
    table(s, MARGIN, 1.45, 7.6, [
        ["Category", "500 pp", "2,000 pp", "What was masked"],
        ["PhoneNumber", "5,280", "22,848", "Mostly 10-digit transaction references"],
        ["Address", "1,958", "8,231", "Customer and merchant locations"],
        ["BankAccountNumber", "136", "555", "Account and reference numbers"],
        ["Person", "104", "383", "Customer and cardholder names"],
        ["CreditCardNumber", "32", "112", "26 / 76 planted; others not investigated"],
        ["CVV, DateTime, Email, SSN", "26 each", "76 each", "Exactly the planted values"],
        ["**Total**", "**7,614**", "**32,433**", ""],
    ], [2.4, 1.0, 1.1, 3.1], size=12, row_h=0.5)
    callout(s, 8.5, 1.45, 4.2, 5.1, "Why it matters", [
        "Over-masking never leaks card data, but it **hides what operations teams need**: every transaction "
        "reference is masked.",
        "General categories (Organization, DateTime) were deliberately left out. They masked every merchant and "
        "every date.",
        "**Fix:** filter by context (e.g. ignore PhoneNumber in a reference column) or drop categories you don't need.",
    ], fill=LIGHT, accent=NAVY, size=13)

    s = d.slide("Processing time", kicker="scripts/benchmark.py", notes=(
        "Document Intelligence dominates: three quarters of the time at 2,000 pages. Larger files ran faster per page. "
        "On Language, be careful with per-page numbers: the 0.3 seconds on the 1-page sample is almost entirely fixed "
        "per-request overhead for one request of 430 characters. Language time scales with characters and the number "
        "of requests, not pages. One request carries up to 25,000 characters, about 20 pages of these statements. At "
        "volume it's about 13 milliseconds per page with 5 requests in parallel, and parallelism made it 3.5 times "
        "faster. All measured from one laptop to East US, at most 3 runs each; expect different numbers from inside Azure. "
        "These are text PDFs; scanned PDFs need full OCR and were not measured."))
    table(s, MARGIN, 1.45, 8.0, [
        ["Stage", "1-page form", "500 pages", "2,000 pages"],
        ["Characters / Language requests", "430 / 1", "598,991 / 26", "2,437,253 / ~104"],
        ["Pre-check", "37 ms", "62 ms", "138 ms"],
        ["Document Intelligence", "2.5 s", "27.4–28.5 s", "87.5 s"],
        ["   per page", "2.5 s", "55–57 ms", "44 ms"],
        ["Language, 5 parallel", "0.3 s", "6.5–11.6 s", "26.5 s"],
        ["   per page", "300 ms*", "13–23 ms", "13 ms"],
        ["Language, 1 at a time", "0.3 s", "24.4 s (49 ms/page)", "not measured"],
        ["Rules, mask, validate", "< 0.01 s", "0.11 s", "not timed separately"],
        ["**End to end**", "**2.8 s**", "**34.4–40.3 s**", "**114.9 s (~1.9 min)**"],
    ], [2.9, 1.4, 1.85, 1.85], size=12, row_h=0.47,
        highlight={(4, c): (MUTED, None) for c in range(4)} | {(6, c): (MUTED, None) for c in range(4)})
    textbox(s, MARGIN, 6.3, 8.0, 0.6,
            "* One 430-character request: almost all fixed per-request overhead, not a per-page rate. "
            "Laptop to East US, up to 3 runs each. Text PDFs only; scans not measured.", size=10, color=MUTED)
    callout(s, 8.95, 1.45, 3.75, 1.65, "Document Intelligence dominates", [
        "87.5 of 114.9 s at 2,000 pages (~76%)."], size=13)
    callout(s, 8.95, 3.25, 3.75, 1.85, "Language scales with characters, not pages", [
        "One request = up to 25,000 chars (~20 pages here)."], fill=AMBER_BG, accent=AMBER, size=13)
    callout(s, 8.95, 5.25, 3.75, 1.4, "Parallelism pays", [
        "24.4 s → 6.9 s with 5 parallel requests."], fill=GREEN_BG, accent=GREEN, size=13)

    # ---------------------------------------------------------------- PART 4
    d.section(4, "Service limits, tested live",
              "Each documented limit deliberately exceeded against the real services, with screenshots")

    s = d.slide("The documented limits we designed around", kicker="Standard tiers, checked November 2026", notes=(
        "These are the numbers the design is built around. The two hard limits for Document Intelligence are 500 MB and "
        "2,000 pages, neither adjustable. For Language, the sync API limits drive the chunking: 5,120 characters per "
        "document and 5 documents per request. Our resource is on the S tier, which we confirmed from the 429 message. "
        "Limits change, so re-check Microsoft's pages before designing around them."))
    textbox(s, MARGIN, 1.4, 5.9, 0.4, "Document Intelligence, Read model (S0)", size=16, bold=True, color=NAVY)
    table(s, MARGIN, 1.85, 5.9, [
        ["Limit", "Value", "Adjustable"],
        ["Max document size", "500 MB", "No"],
        ["Max pages per analysis", "2,000", "No"],
        ["Analyze requests (POST)", "15 per second", "Yes"],
        ["Get-result requests (GET)", "50 per second", "Yes"],
        ["Polling interval", "≥ 2 seconds", "n/a"],
    ], [2.7, 1.8, 1.4], size=13, row_h=0.5)
    textbox(s, 6.8, 1.4, 5.9, 0.4, "Azure AI Language, PII detection", size=16, bold=True, color=NAVY)
    table(s, 6.8, 1.85, 5.9, [
        ["Limit", "Value"],
        ["Characters per document (sync)", "5,120"],
        ["Documents per request (sync)", "5"],
        ["Async job", "25 documents, 125,000 chars total"],
        ["Max request size", "1 MB"],
        ["Rate limit, S0", "100/s, 300/min"],
        ["Rate limit, S (our resource)", "1,000/s, 1,000/min"],
    ], [3.1, 2.8], size=13, row_h=0.5)
    callout(s, MARGIN, 5.55, 12.1, 1.1, "How the pipeline fits inside them", [
        "Chunks of ≤ 5,000 characters, 5 chunks per request (≤ ~25,000 characters, far under 1 MB). "
        "2,000 pages used ~104 requests in 26.5 s, about 235 per minute: inside even S0's 300 per minute."], size=13)

    s = d.slide("What happened when we exceeded each limit", kicker="scripts/test_service_limits.py", notes=(
        "We called the services directly, bypassing our own pre-check, so we were testing the services' enforcement. "
        "Seven limits were enforced as documented. Two surprises: the 2,000-page limit isn't enforced at all, and the "
        "async character limit returns 413 instead of the documented 400. Test 8 was throttled after 585 requests rather "
        "than 1,000, probably because an earlier burst counted toward the same window. Screenshots for each are in "
        "docs/evidence."))
    ok, warn, bad = (GREEN, GREEN_BG), (AMBER, AMBER_BG), (RED, RED_BG)
    table(s, MARGIN, 1.4, 12.1, [
        ["#", "Limit", "What we sent", "What the service did", "Verdict"],
        ["1", "DI: 2,000 pages", "2,001-page PDF", "202, “succeeded”, **2,000 pages returned**, no warning",
         "Silently truncated"],
        ["2", "DI: 500 MB", "501 MiB upload", "400 InvalidContentLength after 160 KB", "Enforced up front"],
        ["3", "DI: 15 analyze/s", "60 requests, 30 parallel", "25 refused with 429, Retry-After: 1", "Enforced"],
        ["4", "Lang: 5,120 chars/doc", "6,000-char + 500-char docs", "Long one InvalidDocument; short one processed",
         "Enforced per document"],
        ["5", "Lang: 5 docs (sync)", "6 documents", "400 InvalidDocumentBatch", "Enforced"],
        ["6", "Lang: 25 docs (async)", "26 documents", "400 InvalidDocumentBatch", "Enforced"],
        ["7", "Lang: 125,000 chars (async)", "127,500 characters", "**413** (documentation says 400)", "Enforced, other code"],
        ["8", "Lang: 1,000/min (S)", "1,100 requests, 40 parallel", "505 refused with 429, Retry-After: 45", "Enforced"],
        ["9", "Our pre-check", "2,001 pages; 501 MiB", "Both rejected before any Azure call", "Enforced by our code"],
    ], [0.4, 2.5, 2.6, 4.4, 2.2], size=12, row_h=0.5,
        highlight={(1, 4): bad, (2, 4): ok, (3, 4): ok, (4, 4): ok, (5, 4): ok, (6, 4): ok, (7, 4): warn,
                   (8, 4): ok, (9, 4): ok})
    textbox(s, MARGIN, 6.5, 12.1, 0.4,
            "DI = Document Intelligence (S0). Lang = Azure AI Language (S). Run November 22, 2026. "
            "Dropped TLS connections from the test machine are shown separately and not counted.", size=10, color=MUTED)

    s = d.slide("Key finding: files over 2,000 pages are silently truncated", kicker="Evidence 01", notes=(
        "This is the most important result of the project. We sent a 2,001-page PDF straight to Document Intelligence. "
        "It accepted it, reported succeeded, and returned 2,000 pages. No error, no warning. If a card form were on page "
        "2,001, it would never be scanned: in mask mode it would come back unmasked, and in block mode the document "
        "would pass as clean. The fix is two checks: count pages before calling the service, and after extraction fail "
        "closed if fewer pages came back than the file has."))
    picture(s, os.path.join(EVIDENCE, "01-document-intelligence-2001-pages.png"), MARGIN, 1.4, 12.1, 3.05)
    callout(s, MARGIN, 4.75, 5.95, 1.9, "Risk", [
        "Card data after page 2,000 is **never scanned**. Mask mode returns it unmasked; block mode passes the "
        "document as clean."], fill=RED_BG, accent=RED, size=13)
    callout(s, MARGIN + 6.15, 4.75, 5.95, 1.9, "Fix, now in the pipeline", [
        "**1.** Pre-check counts pages inside the file and rejects > 2,000.",
        "**2.** After extraction: pages returned ≠ pages counted → fail closed."],
        fill=GREEN_BG, accent=GREEN, size=13)

    s = d.slide("Evidence: Document Intelligence size and rate limits", kicker="Evidence 02 and 03", notes=(
        "The 500 MB limit is enforced at the door: the service rejected the upload from its declared Content-Length after "
        "only 160 KB was sent. The rate limit returned 429 with Retry-After of 1 second, and the message names the "
        "pricing tier, which is a handy way to confirm the tier."))
    picture(s, os.path.join(EVIDENCE, "02-document-intelligence-501-mb.png"), MARGIN, 1.35, 12.1, 2.45)
    picture(s, os.path.join(EVIDENCE, "03-document-intelligence-rate-limit-429.png"), MARGIN, 3.9, 12.1, 2.85)

    s = d.slide("Evidence: Language batch and rate limits", kicker="Evidence 07 and 08", notes=(
        "The async character limit is enforced, but with 413 Payload Too Large rather than the documented 400, so "
        "clients must handle both. The Language rate limit returned Retry-After of 45 seconds. A fixed short backoff "
        "would keep hitting the limit; honor Retry-After exactly. Screenshots 04 to 06 and 09 to 10 are in docs/evidence."))
    picture(s, os.path.join(EVIDENCE, "07-language-125000-characters-async.png"), MARGIN, 1.35, 12.1, 2.35)
    picture(s, os.path.join(EVIDENCE, "08-language-rate-limit-429.png"), MARGIN, 3.85, 12.1, 2.9)

    s = d.slide("What the limit tests mean for the design", kicker="Takeaways", notes=(
        "Five takeaways for anyone building on these services, not just this project."))
    takeaways = [
        ("Enforce the 2,000-page limit yourself",
         "Document Intelligence won't. Count pages before the call and compare after it.", RED),
        ("Size is enforced at the door",
         "An oversized file is rejected from its declared size, so an early size check costs nothing extra.", BLUE),
        ("Honor Retry-After exactly",
         "Document Intelligence asked for 1 s, Language for 45 s. A fixed short backoff keeps hitting the limit.", BLUE),
        ("Handle 413 as well as 400",
         "The async Language API returned 413 where the documentation says 400.", AMBER),
        ("Read the tier from a 429",
         "Both services name the pricing tier in their 429 message.", BLUE),
    ]
    for i, (title, body, color) in enumerate(takeaways):
        y = 1.5 + i * 1.03
        panel(s, MARGIN, y, 12.1, 0.88, fill=LIGHT)
        mark = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(MARGIN), Inches(y), Inches(0.1), Inches(0.88))
        mark.fill.solid()
        mark.fill.fore_color.rgb = color
        mark.line.fill.background()
        textbox(s, MARGIN + 0.3, y + 0.08, 4.2, 0.75, title, size=16, bold=True, color=NAVY, anchor=MSO_ANCHOR.MIDDLE)
        textbox(s, MARGIN + 4.6, y + 0.08, 7.4, 0.75, body, size=14, anchor=MSO_ANCHOR.MIDDLE)

    # ---------------------------------------------------------------- PART 5
    d.section(5, "Target architecture and next steps",
              "How this would run on Azure, what we decided, and what's still open")

    s = d.slide("Target architecture: logical flow", kicker="docs/architecture.md", notes=(
        "Asynchronous by design: intake returns in seconds with a job ID, processing runs in a worker, and the caller "
        "polls or gets a webhook. Measured processing times are too long to hold a web request open. Only the pre-check "
        "and the worker logic exist in the repo today; the rest is design."))
    picture(s, logical_png, MARGIN, 1.3, 12.1, 5.65)

    s = d.slide("Target architecture: Azure implementation", kicker="docs/technical-architecture.md", notes=(
        "The same flow with real Azure services and official icons. Components tagged IN REPO have their logic in "
        "languageservice.py. Walk through the request flow on the next slide."))
    picture(s, technical_png, MARGIN, 1.3, 12.1, 5.65)

    s = d.slide("Request flow, end to end", kicker="Target design, not deployed", notes=(
        "Key idea: the file never passes through API Management. The client sends metadata, gets a write-only SAS URL, "
        "and uploads directly to a quarantine container. Defender scans it; Event Grid triggers the Intake Function, "
        "which runs the authoritative checks on the real file. Then a Service Bus message triggers the worker. The caller "
        "gets the result from the Job-status Function, which only answers the job's owner."))
    flow = [
        ("1", "App Gateway + WAF", "TLS, web firewall"),
        ("2", "API Management", "Entra token, rate limit, declared size/type"),
        ("3", "Create-job Function", "Job record with owner oid; SAS upload URL"),
        ("4", "Blob quarantine", "Client uploads directly; never via APIM"),
        ("5", "Defender for Storage", "Malware scan → Event Grid"),
        ("6", "Intake Function", "Real size, type, pages (precheck())"),
        ("7", "Service Bus", "One message per job; retries, dead-letter"),
        ("8", "Worker Function", "DI → chunk → Language → rules → validate"),
        ("9", "Blob results", "Masked JSON or blocked; raw file deleted"),
        ("10", "Job-status Function", "GET /jobs/{id}: owner only, else 404"),
    ]
    bw, bh = 2.25, 1.75
    for i, (n, name, desc) in enumerate(flow):
        row, col = divmod(i, 5)
        x = MARGIN + col * (bw + 0.21)
        y = 1.5 + row * (bh + 0.55)
        in_repo = n in ("6", "8")
        panel(s, x, y, bw, bh, fill=GREEN_BG if in_repo else LIGHT, border=GREEN if in_repo else LINE)
        textbox(s, x + 0.1, y + 0.1, bw - 0.2, 0.35, n, size=16, bold=True, color=GREEN if in_repo else BLUE)
        textbox(s, x + 0.1, y + 0.45, bw - 0.2, 0.5, name, size=13, bold=True, color=NAVY)
        textbox(s, x + 0.1, y + 0.95, bw - 0.2, 0.8, desc, size=11)
        if col < 4:
            arrow(s, x + bw + 0.0, y + bh / 2 - 0.12, w=0.21, h=0.24)
    textbox(s, MARGIN, 6.2, 12.1, 0.5,
            "Green = logic exists in languageservice.py today.  API: POST /jobs → 202 + upload URL;  "
            "GET /jobs/{id} → 202 running, 200 masked JSON, 422 blocked, 404 not yours.", size=12, color=MUTED)

    s = d.slide("Design decisions and why", kicker="From the design reviews", notes=(
        "Each of these came out of a review question. Blob instead of Cosmos DB: one JSON blob per job with ETag "
        "concurrency is enough; no second data store to secure. Functions instead of Container Apps: one compute service, "
        "a native Service Bus trigger, and the measured jobs fit; revisit if scanned documents exceed the timeout. "
        "We compared with Krishnan Sriram's gateway-only design and adopted its ownership, key-less auth, and block "
        "mode ideas, but moved the file and the processing out of API Management."))
    table(s, MARGIN, 1.4, 12.1, [
        ["Decision", "Why", "Alternative considered"],
        ["File uploaded straight to Blob with a SAS (valet key)",
         "Files up to 500 MB; APIM can't inspect large bodies or count PDF pages", "File through APIM (gateway-only design)"],
        ["Keep API Management", "Entra token validation, rate limits per client, early metadata checks, one API surface",
         "Functions exposed directly"],
        ["Blob Storage as the only data store", "One JSON blob per job, ETag concurrency, index tags, lifecycle deletion",
         "Cosmos DB: another service to secure"],
        ["Worker on Functions (Service Bus trigger)", "One compute service; scales with the queue; 2,000 pages took ~2 min",
         "Container Apps, if scans exceed timeouts"],
        ["Checks split: APIM early, Intake Function authoritative", "Declared size and type can lie; real file can't",
         "All checks in APIM: can't see the file"],
        ["Jobs bound to the caller's Entra oid", "Others get 404; a guessed job ID reveals nothing", "Job ID as the only secret"],
        ["No keys: managed identity, disableLocalAuth, private endpoints",
         "Nothing to leak; card data stays off the public internet", "Keys in Key Vault"],
    ], [3.9, 4.9, 3.3], size=12, row_h=0.6)

    s = d.slide("Mask or block: a business decision", kicker="--pci-mode", notes=(
        "Both modes are implemented and were tested live. Block mode is safer when the business doesn't need documents "
        "that contain card data, because it doesn't depend on catching every card field. Mask mode is for workflows that "
        "need the rest of the document. This is a decision for the business and compliance, not engineering."))
    callout(s, MARGIN, 1.5, 5.95, 2.6, "mask (default)  →  HTTP 200", [
        "Masks every card number, CVV, expiry, and personal value.",
        "Returns masked text and entity metadata.",
        "**For workflows that need the rest of the document.**",
    ], size=14)
    callout(s, MARGIN + 6.15, 1.5, 5.95, 2.6, "block  →  HTTP 422", [
        "Any card number or CVV found: reject the whole document.",
        "Returns status: blocked and the categories found. No text, no positions.",
        "**Doesn't depend on catching every card field.**",
    ], fill=RED_BG, accent=RED, size=14)
    table(s, MARGIN, 4.4, 12.1, [
        ["Live test (block mode)", "Result", "Time"],
        ["1-page card form", "blocked: CVV, CreditCardNumber", "DI 2.5 s, Language 0.3 s"],
        ["Clean 1-page document", "ok", "DI 3.5 s, Language 0.2 s"],
        ["500-page statement batch", "blocked: CVV, CreditCardNumber", "DI 28.5 s, Language 6.5 s"],
    ], [4, 4.6, 3.5], size=13, row_h=0.48)

    s = d.slide("Honest assessment: is this enterprise-ready?", kicker="Not yet, and here's why", notes=(
        "When we asked whether this is how a fintech would really build it: the shape is sound, async intake, queue, "
        "worker, fail closed, defense in depth. But several things are open before it touches real card data. PCI scope "
        "is the big one: everything that receives full card numbers is in the cardholder data environment. Many "
        "organizations would rather tokenize card data upstream so it never reaches a document pipeline. Preview "
        "features need compliance sign-off. And all accuracy numbers come from synthetic English text PDFs."))
    callout(s, MARGIN, 1.5, 5.95, 5.1, "What's solid", [
        "Async intake, queue-driven worker, results by job ID",
        "Defense in depth: explicit categories, rules, output check, fail closed",
        "Page-count guard against silent truncation",
        "Block mode for card data",
        "Every limit tested live, with evidence",
        "Key-less, private-endpoint design with least-privilege roles",
    ], fill=GREEN_BG, accent=GREEN, size=14)
    callout(s, MARGIN + 6.15, 1.5, 5.95, 5.1, "What's open", [
        "**PCI scope:** upload storage, worker, both AI resources, and logs are all in the cardholder data environment",
        "**Tokenization:** consider removing card data upstream so it never reaches a document pipeline",
        "**Compliance:** confirm the services' PCI coverage and preview-feature use with your QSA",
        "**Accuracy:** only synthetic English text PDFs tested. No scans, handwriting, or other languages",
        "**Not deployed:** keys still in .env; target architecture untested",
    ], fill=AMBER_BG, accent=AMBER, size=14)

    s = d.slide("Known gaps", kicker="From the README", notes=(
        "The full list with suggested fixes is in the README's Known gaps section. These are the ones that matter most."))
    table(s, MARGIN, 1.4, 12.1, [
        ["Gap", "Risk", "Suggested fix"],
        ["CVV and expiry rely on preview features", "Behavior can change between versions",
         "Keep rules and output check; compliance sign-off; re-score on every version change"],
        ["~15% of names in capitals missed", "Personal data stays readable",
         "Detect on a title-cased copy; match against the customer record; human review"],
        ["Heavy over-masking", "32,433 entities on 2,000 pages; references hidden", "Filter by context; drop unneeded categories"],
        ["Page counting: PDF, TIFF, images only", "PPTX, XLS, DOCX can't be checked for truncation",
         "Count slides and sheets, or reject those types"],
        ["Unreliable network path from the test machine", "17–23% TLS handshake failures (retries now handle it)",
         "Investigate proxy/VPN/firewall; retest from Azure with private endpoints"],
        ["Concurrency limited per process", "Several workers can exceed the Language rate limit together",
         "Shared rate limiter across workers"],
        ["Keys in .env", "Key leakage", "Managed identity; disableLocalAuth=true"],
    ], [3.6, 4.0, 4.5], size=12, row_h=0.6)

    s = d.slide("Recommendations for large documents", kicker="File size and pages", notes=(
        "Practical sizing guidance from the measurements. Hard limits can't be raised: reject or split. Don't rely on "
        "Document Intelligence to reject page counts. Benchmark with real scans before sizing anything."))
    table(s, MARGIN, 1.4, 12.1, [
        ["Document", "Recommendation"],
        ["Over 500 MB or over 2,000 pages", "Hard limits. Reject at upload or split before submitting. "
         "**Don't rely on Document Intelligence to reject > 2,000 pages**"],
        ["500 to 2,000 pages", "One call works: 87.5 s for 2,000 pages, 114.9 s end to end. Split into page ranges "
         "(pages parameter) to go faster or limit the cost of a failure"],
        ["Up to 500 pages, text PDF", "One call is fine: 34–40 s end to end"],
        ["Scanned PDFs and images", "Larger files, longer OCR. Not measured here: benchmark with real scans"],
    ], [3.3, 8.8], size=13, row_h=0.62)
    bullets(s, MARGIN, 4.75, 12.1, 2.0, [
        "**Validate before upload:** size from metadata, pages counted inside the file (~25 ms for 500 pages, 57–99 ms for 2,000)",
        "**Throughput:** S0 Language allows 300 requests/min ≈ 6,000 pages/min at ~1,219 characters per page, across all workers",
        "**Request only the categories you need;** use a shared rate limiter and honor Retry-After",
    ], size=14, spacing=6)

    s = d.slide("Proposed next steps", kicker="For discussion", notes=(
        "Suggested order: first the things that block any real-data use, compliance and real documents, then the "
        "engineering items, then a sandbox deployment to test the network path that was flaky here."))
    steps = [
        ("Compliance", "Review PCI scope, tokenization options, and preview-feature use with the QSA and security team"),
        ("Real documents", "Labeled test set from our own layouts (incl. scans) with synthetic values; track recall per category"),
        ("Accuracy", "Improve name detection; filter over-masking by context"),
        ("Security", "Entra ID auth in the code, disableLocalAuth on both AI resources; pass Document Intelligence a blob URL"),
        ("Deploy", "Sandbox deployment of the target architecture with private endpoints; retest network and timings"),
        ("Operate", "Alert on rule_only_detections > 0; shared rate limiter; re-score on every API or model change"),
    ]
    for i, (tag, text) in enumerate(steps):
        y = 1.45 + i * 0.86
        panel(s, MARGIN, y, 2.3, 0.7, fill=NAVY)
        textbox(s, MARGIN, y, 2.3, 0.7, tag, size=15, bold=True, color=WHITE, align=PP_ALIGN.CENTER,
                anchor=MSO_ANCHOR.MIDDLE)
        textbox(s, MARGIN + 2.5, y, 9.6, 0.7, text, size=15, anchor=MSO_ANCHOR.MIDDLE)

    s = d.slide("Where to find everything", kicker=REPO_URL, notes=(
        "Everything is reproducible from the repo: the test documents are committed, and every script that produced a "
        "number on these slides is listed here. Questions?"))
    table(s, MARGIN, 1.4, 12.1, [
        ["Path", "What it is"],
        ["README.md", "Full write-up: limits, test results, evidence, known gaps, enterprise guidance"],
        ["languageservice.py", "The pipeline: pre-check, Document Intelligence, Language, rules, mask, validate, mask/block"],
        ["docs/architecture.md, docs/technical-architecture.md", "Target architecture: logical flow and Azure implementation"],
        ["docs/evidence/", "Service-limit screenshots and plain-text transcripts"],
        ["test_data/", "500- and 2,000-page batches, ground truth, pipeline output"],
        ["scripts/", "Test-data generator, scorer, benchmark, limit tests, diagram and deck builders"],
        ["docs/presentation/", "This deck (PPTX and PDF), built by scripts/build_presentation.py"],
    ], [4.6, 7.5], size=13, row_h=0.55)
    textbox(s, MARGIN, 6.05, 12.1, 0.5, "Questions and discussion", size=22, bold=True, color=NAVY,
            align=PP_ALIGN.CENTER)

    return d


def to_pdf(pptx_path):
    soffice = next((c for c in SOFFICE_CANDIDATES if shutil.which(c) or os.path.exists(c)), None)
    if not soffice:
        print("LibreOffice not found: skipped the PDF copy")
        return
    subprocess.run([soffice, "--headless", "--convert-to", "pdf", "--outdir", OUT_DIR, pptx_path],
                   capture_output=True, check=True)
    print(f"wrote {os.path.relpath(pptx_path[:-5] + '.pdf', ROOT)}")


if __name__ == "__main__":
    os.makedirs(OUT_DIR, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        deck = build(tmp)
        deck.prs.save(OUT_PPTX)
    print(f"wrote {os.path.relpath(OUT_PPTX, ROOT)} ({deck.count} slides)")
    to_pdf(OUT_PPTX)
