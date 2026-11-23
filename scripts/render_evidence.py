"""
Renders the service-limit test transcripts in docs/evidence/logs/ as terminal-style PNG
screenshots in docs/evidence/, using headless Chrome.

The images show the transcripts' text exactly as saved by scripts/test_service_limits.py;
only colors and layout are added.

Usage (from the project root):
  python scripts/render_evidence.py
"""

import html
import math
import os
import subprocess
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(ROOT, "docs", "evidence", "logs")
OUT_DIR = os.path.join(ROOT, "docs", "evidence")
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

# Output order and file names
ORDER = [
    ("di-pages", "01-document-intelligence-2001-pages"),
    ("di-size", "02-document-intelligence-501-mb"),
    ("di-rate", "03-document-intelligence-rate-limit-429"),
    ("lang-chars", "04-language-5120-characters"),
    ("lang-docs-sync", "05-language-6-documents-sync"),
    ("lang-docs-async", "06-language-26-documents-async"),
    ("lang-chars-async", "07-language-125000-characters-async"),
    ("lang-rate", "08-language-rate-limit-429"),
    ("pipeline-precheck", "09-pipeline-precheck-rejections"),
    ("pipeline-results", "10-pipeline-results-500-and-2000-pages"),
]
WIDTH = 1500
CHARS_PER_LINE = 158
LINE_PX = 22


def color_for(line):
    if line.startswith("$"):
        return "#7ee787"
    if line.startswith("#"):
        return "#8b949e"
    if line.startswith("Verdict"):
        if "SILENTLY" in line or "page says 400" in line:
            return "#f2cc60"
        if "ENFORCED" in line or "REJECTED BY" in line:
            return "#56d364"
        return "#ff7b72"
    if line.startswith(("Error", "429 body", '{"status": "error"')):
        return "#ffa198"
    if "HTTP 429" in line or "connection error" in line:
        return "#f2cc60"
    return "#e6edf3"


def render(test_id, name):
    path = os.path.join(LOG_DIR, f"{test_id}.txt")
    if not os.path.exists(path):
        print(f"skip {test_id}: no transcript")
        return
    lines = open(path, encoding="utf-8").read().rstrip("\n").split("\n")
    title = next((l[2:] for l in lines if l.startswith("# ") and not l.startswith("# Run")), test_id)
    body = "".join(
        f'<div style="color:{color_for(l)};{"font-weight:700;" if l.startswith("Verdict") else ""}">'
        f'{html.escape(l) or "&nbsp;"}</div>' for l in lines)
    rows = sum(max(1, math.ceil(len(l) / CHARS_PER_LINE)) for l in lines)
    height = rows * LINE_PX + 110
    page = f"""<!doctype html><html><head><meta charset="utf-8"><style>
      body {{ margin:0; background:#f6f8fa; }}
      .win {{ margin:16px; border-radius:10px; overflow:hidden; box-shadow:0 2px 8px rgba(0,0,0,.25); background:#0d1117; }}
      .bar {{ background:#21262d; height:34px; display:flex; align-items:center; padding:0 14px; gap:8px;
              font:13px -apple-system,Segoe UI,Helvetica,Arial,sans-serif; color:#c9d1d9; }}
      .dot {{ width:12px; height:12px; border-radius:50%; display:inline-block; }}
      .t {{ margin-left:10px; }}
      pre {{ margin:0; padding:16px 18px 20px; font:14px/22px Menlo,Consolas,monospace; white-space:pre-wrap; word-break:break-word; }}
    </style></head><body><div class="win">
      <div class="bar"><span class="dot" style="background:#ff5f56"></span><span class="dot" style="background:#ffbd2e"></span>
      <span class="dot" style="background:#27c93f"></span><span class="t">Service limit evidence: {html.escape(title)}</span></div>
      <pre>{body}</pre></div></body></html>"""
    with tempfile.TemporaryDirectory() as tmp:
        page_path = os.path.join(tmp, "page.html")
        with open(page_path, "w", encoding="utf-8") as f:
            f.write(page)
        out = os.path.join(OUT_DIR, f"{name}.png")
        subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                        "--force-device-scale-factor=1", f"--window-size={WIDTH},{height}",
                        f"--screenshot={out}", f"file://{page_path}"], capture_output=True, check=True)
    print(f"wrote {os.path.relpath(out, ROOT)}")


if __name__ == "__main__":
    for test_id, name in ORDER:
        render(test_id, name)
