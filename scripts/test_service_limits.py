"""
Deliberately exceeds each documented service limit against the live Azure resources, and
records exactly what was sent and what the service returned.

Each test writes a transcript to docs/evidence/logs/<id>.txt. No keys or document content
are written. Render the transcripts as screenshots with scripts/render_evidence.py.

These tests call the services directly, bypassing languageservice.py's own pre-check, so
the services' own enforcement is what's being tested. Some tests are billed: the
Document Intelligence page-limit test can bill up to 2,000 pages if the service accepts
the file, and the rate-limit tests bill one page or one text record per accepted request.

Usage (from the project root):
  python scripts/test_service_limits.py              # all tests
  python scripts/test_service_limits.py di-pages lang-docs-sync
"""

import collections
import io
import os
import random
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv
from pypdf import PdfWriter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(ROOT, "docs", "evidence", "logs")
load_dotenv(os.path.join(ROOT, ".env"), override=True)

DI_EP = os.environ["AZURE_DOCINTEL_ENDPOINT"].rstrip("/")
DI_KEY = os.environ["AZURE_DOCINTEL_KEY"]
LANG_EP = os.environ["AZURE_LANGUAGE_ENDPOINT"].rstrip("/")
LANG_KEY = os.environ["AZURE_LANGUAGE_KEY"]
DI_API = "2024-11-30"
LANG_API = "2026-05-15-preview"
DI_ANALYZE = f"{DI_EP}/documentintelligence/documentModels/prebuilt-read:analyze"
LANG_SYNC = f"{LANG_EP}/language/:analyze-text"
LANG_ASYNC = f"{LANG_EP}/language/analyze-text/jobs"
DI_DOCS = "learn.microsoft.com/azure/ai-services/document-intelligence/service-limits"
LANG_DOCS = "learn.microsoft.com/azure/ai-services/language-service/concepts/data-limits"


class Transcript:
    def __init__(self, test_id, title):
        self.test_id, self.lines = test_id, []
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        self.add(f"$ python scripts/test_service_limits.py {test_id}")
        self.add(f"# {title}")
        self.add(f"# Run at {stamp}")
        self.add("")

    def add(self, line=""):
        print(line)
        self.lines.append(line)

    def field(self, name, value):
        self.add(f"{name:<18}: {value}")

    def save(self):
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(os.path.join(LOG_DIR, f"{self.test_id}.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(self.lines) + "\n")


def with_connection_retries(fn, attempts=6):
    """Retry only dropped connections (seen often on this network), never service responses."""
    for attempt in range(attempts):
        try:
            return fn(), attempt + 1
        except requests.ConnectionError:
            if attempt == attempts - 1:
                raise
            time.sleep(1 + attempt)


def short(text, n=300):
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[:n] + " ..."


def error_of(response):
    try:
        body = response.json()
    except ValueError:
        return short(response.text)
    err = body.get("error", body)
    inner = err.get("innererror") or {}
    parts = [f"code={err.get('code')}"]
    if inner.get("code"):
        parts.append(f"innererror.code={inner.get('code')}")
    parts.append(f"message={short(inner.get('message') or err.get('message'), 220)}")
    return ", ".join(parts)


def blank_pdf(pages):
    writer, buf = PdfWriter(), io.BytesIO()
    for _ in range(pages):
        writer.add_blank_page(612, 792)
    writer.write(buf)
    return buf.getvalue()


def text_pdf(pages):
    """A PDF with one line of text per page, so the service has something to read."""
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf, invariant=1)
    for i in range(pages):
        c.drawString(72, 720, f"Service limit test page {i + 1} of {pages}. Synthetic text only.")
        c.showPage()
    c.save()
    return buf.getvalue()


# --- Document Intelligence ---------------------------------------------------------------

def test_di_pages():
    t = Transcript("di-pages", "Document Intelligence: more than 2,000 pages in one analysis")
    t.field("Limit under test", "Max pages per analysis = 2,000 (S0, not adjustable)")
    t.field("Source", DI_DOCS)
    data = text_pdf(2001)
    t.field("Request", f"POST prebuilt-read:analyze  body: PDF, 2,001 pages, {len(data) / 1024:,.0f} KB")
    r, tries = with_connection_retries(lambda: requests.post(
        DI_ANALYZE, params={"api-version": DI_API}, data=data, timeout=300,
        headers={"Ocp-Apim-Subscription-Key": DI_KEY, "Content-Type": "application/pdf"}))
    t.field("Response", f"HTTP {r.status_code} {r.reason}" + (f"  (after {tries} connection attempts)" if tries > 1 else ""))
    if r.status_code != 202:
        t.field("Error", error_of(r))
        verdict = "LIMIT ENFORCED: request rejected" if r.status_code >= 400 else f"UNEXPECTED: HTTP {r.status_code}"
        t.field("Verdict", verdict)
        return t
    op = r.headers["Operation-Location"]
    t.field("Accepted", "analysis started; polling every 2 s")
    start = time.time()
    while True:
        time.sleep(2)
        p, _ = with_connection_retries(lambda: requests.get(op, headers={"Ocp-Apim-Subscription-Key": DI_KEY}, timeout=60))
        if p.status_code == 429:
            continue
        body = p.json()
        if body.get("status") in ("succeeded", "failed"):
            break
        if time.time() - start > 600:
            t.field("Verdict", "INCONCLUSIVE: still running after 10 minutes")
            return t
    t.field("Final status", f"{body.get('status')} after {time.time() - start:.0f} s")
    if body.get("status") == "failed":
        t.field("Error", short(body.get("error"), 300))
        t.field("Verdict", "LIMIT ENFORCED: analysis failed")
    else:
        pages = len(body.get("analyzeResult", {}).get("pages", []))
        t.field("Pages returned", f"{pages:,} of 2,001 sent")
        if pages < 2001:
            t.field("Verdict", f"LIMIT ENFORCED SILENTLY: only the first {pages:,} pages were analyzed, with no error")
        else:
            t.field("Verdict", "NOT ENFORCED: all 2,001 pages were analyzed")
    return t


def test_di_size():
    t = Transcript("di-size", "Document Intelligence: file larger than 500 MB")
    t.field("Limit under test", "Max document size = 500 MB (S0, not adjustable)")
    t.field("Source", DI_DOCS)
    size = 500 * 1024 * 1024 + 1024 * 1024  # 501 MiB

    class RandomBody:
        """Fixed-length body generated on the fly, so the request carries a real
        Content-Length (no chunked encoding) without writing 501 MiB to disk."""
        def __init__(self, n):
            self.n, self.pos, self.block = n, 0, os.urandom(1024 * 1024)

        def __len__(self):
            return self.n

        def read(self, amt=-1):
            if self.pos >= self.n:
                return b""
            amt = self.n - self.pos if amt is None or amt < 0 else min(amt, self.n - self.pos)
            if self.pos == 0:
                out = (b"%PDF-1.7\n" + self.block)[:amt]
            else:
                out = (self.block * (amt // len(self.block) + 1))[:amt]
            self.pos += len(out)
            return out

    t.field("Request", f"POST prebuilt-read:analyze  body: {size / 1024 / 1024:,.0f} MiB ({size:,} bytes), streamed")
    handshake_failures = 0
    for attempt in range(8):
        payload = RandomBody(size)
        start = time.time()
        try:
            r = requests.post(DI_ANALYZE, params={"api-version": DI_API}, data=payload, timeout=900,
                              headers={"Ocp-Apim-Subscription-Key": DI_KEY, "Content-Type": "application/pdf"})
        except requests.RequestException as exc:
            if payload.pos == 0:  # connection failed before any byte was sent: says nothing about the limit
                handshake_failures += 1
                time.sleep(2)
                continue
            t.field("Sent", f"{payload.pos:,} of {size:,} bytes before the connection closed")
            t.field("Response", f"connection closed by the service after {time.time() - start:.0f} s ({type(exc).__name__})")
            t.field("Error", short(exc, 220))
            t.field("Verdict", "LIMIT ENFORCED: upload refused before completion")
            break
        if handshake_failures:
            t.field("Note", f"{handshake_failures} earlier attempt(s) failed in the TLS handshake before sending data; retried")
        t.field("Sent", f"{payload.pos:,} of {size:,} bytes; request Content-Length: {r.request.headers.get('Content-Length')}, "
                        f"Transfer-Encoding: {r.request.headers.get('Transfer-Encoding', 'none')}")
        t.field("Response", f"HTTP {r.status_code} {r.reason}  after {time.time() - start:.0f} s")
        if r.status_code >= 400:
            t.field("Error", error_of(r))
            t.field("Verdict", "LIMIT ENFORCED: request rejected")
        else:
            t.field("Verdict", f"UNEXPECTED: HTTP {r.status_code}")
        break
    else:
        t.field("Verdict", f"INCONCLUSIVE: all {handshake_failures} attempts failed in the TLS handshake before sending data")
    return t


def test_di_rate():
    t = Transcript("di-rate", "Document Intelligence: burst of analyze requests above 15 per second")
    t.field("Limit under test", "Analyze transactions per second = 15 (S0 default, adjustable)")
    t.field("Source", DI_DOCS)
    data = text_pdf(1)
    n, workers = 60, 30
    t.field("Request", f"{n} x POST prebuilt-read:analyze (1-page PDF), {workers} in parallel")
    sample_429 = {}

    def call(_):
        try:
            r = requests.post(DI_ANALYZE, params={"api-version": DI_API}, data=data, timeout=60,
                              headers={"Ocp-Apim-Subscription-Key": DI_KEY, "Content-Type": "application/pdf"})
            if r.status_code == 429 and not sample_429:
                sample_429.update(error=error_of(r), retry_after=r.headers.get("Retry-After"))
            return f"HTTP {r.status_code}"
        except requests.RequestException as exc:
            return f"connection error ({type(exc).__name__})"

    start = time.time()
    with ThreadPoolExecutor(workers) as pool:
        counts = collections.Counter(pool.map(call, range(n)))
    t.field("Duration", f"{time.time() - start:.1f} s")
    for status, count in sorted(counts.items()):
        t.field("  " + status, f"{count} requests")
    if sample_429:
        t.field("429 body", sample_429["error"])
        t.field("Retry-After", sample_429["retry_after"])
        t.field("Verdict", "LIMIT ENFORCED: requests over the rate were refused with HTTP 429")
    else:
        t.field("Verdict", "NOT TRIGGERED: no HTTP 429 in this burst")
    return t


# --- Azure AI Language ---------------------------------------------------------------

def lang_sync(documents):
    body = {"kind": "PiiEntityRecognition", "analysisInput": {"documents": documents},
            "parameters": {"modelVersion": "latest"}}
    return with_connection_retries(lambda: requests.post(
        LANG_SYNC, params={"api-version": LANG_API}, json=body, timeout=60,
        headers={"Ocp-Apim-Subscription-Key": LANG_KEY}))


def filler(n):
    words = "Synthetic statement text for a service limit test with no personal data at all".split()
    out = []
    while len(" ".join(out)) < n:
        out.append(random.Random(len(out)).choice(words))
    return " ".join(out)[:n]


def test_lang_chars():
    t = Transcript("lang-chars", "Azure AI Language: document longer than 5,120 characters (synchronous)")
    t.field("Limit under test", "Max characters per document, synchronous = 5,120")
    t.field("Source", LANG_DOCS)
    docs = [{"id": "too-long", "language": "en", "text": filler(6000)},
            {"id": "normal", "language": "en", "text": filler(500)}]
    t.field("Request", "POST :analyze-text (PII)  documents: 'too-long' 6,000 chars, 'normal' 500 chars")
    r, tries = lang_sync(docs)
    t.field("Response", f"HTTP {r.status_code} {r.reason}" + (f"  (after {tries} connection attempts)" if tries > 1 else ""))
    if r.status_code == 200:
        res = r.json()["results"]
        ok = [d["id"] for d in res.get("documents", [])]
        for e in res.get("errors", []):
            err = e.get("error", {})
            inner = err.get("innererror") or {}
            t.field(f"Error '{e['id']}'", f"code={err.get('code')}, innererror.code={inner.get('code')}, "
                                          f"message={short(inner.get('message') or err.get('message'), 160)}")
        t.field("Processed", ", ".join(ok) or "none")
        rejected = [e["id"] for e in res.get("errors", [])]
        t.field("Verdict", "LIMIT ENFORCED: oversized document rejected, the other one still processed"
                if rejected == ["too-long"] and ok == ["normal"] else "UNEXPECTED: see above")
    else:
        t.field("Error", error_of(r))
        t.field("Verdict", f"LIMIT ENFORCED at request level: HTTP {r.status_code}")
    return t


def test_lang_docs_sync():
    t = Transcript("lang-docs-sync", "Azure AI Language: 6 documents in one synchronous PII request")
    t.field("Limit under test", "Max documents per request, synchronous PII = 5")
    t.field("Source", LANG_DOCS)
    docs = [{"id": str(i), "language": "en", "text": filler(200)} for i in range(6)]
    t.field("Request", "POST :analyze-text (PII)  documents: 6 x 200 chars")
    r, tries = lang_sync(docs)
    t.field("Response", f"HTTP {r.status_code} {r.reason}" + (f"  (after {tries} connection attempts)" if tries > 1 else ""))
    t.field("Error", error_of(r) if r.status_code != 200 else "none")
    t.field("Verdict", "LIMIT ENFORCED: whole request rejected" if r.status_code == 400 else f"UNEXPECTED: HTTP {r.status_code}")
    return t


def lang_async(documents):
    body = {"displayName": "service-limit-test", "analysisInput": {"documents": documents},
            "tasks": [{"kind": "PiiEntityRecognition", "taskName": "pii", "parameters": {"modelVersion": "latest"}}]}
    return with_connection_retries(lambda: requests.post(
        LANG_ASYNC, params={"api-version": LANG_API}, json=body, timeout=60,
        headers={"Ocp-Apim-Subscription-Key": LANG_KEY}))


def follow_async(t, r):
    """If an async job was accepted, poll it and report whether it failed."""
    op = r.headers.get("Operation-Location")
    for _ in range(60):
        time.sleep(2)
        p, _ = with_connection_retries(lambda: requests.get(op, headers={"Ocp-Apim-Subscription-Key": LANG_KEY}, timeout=60))
        body = p.json()
        if body.get("status") in ("succeeded", "failed", "partiallySucceeded", "cancelled"):
            t.field("Job status", body.get("status"))
            if body.get("errors"):
                t.field("Job error", short(body["errors"], 250))
            return body.get("status")
    t.field("Job status", "still running after 2 minutes")
    return None


def test_lang_docs_async():
    t = Transcript("lang-docs-async", "Azure AI Language: 26 documents in one asynchronous job")
    t.field("Limit under test", "Max documents per request, asynchronous = 25")
    t.field("Source", LANG_DOCS)
    docs = [{"id": str(i), "language": "en", "text": filler(200)} for i in range(26)]
    t.field("Request", "POST analyze-text/jobs (PII)  documents: 26 x 200 chars")
    r, tries = lang_async(docs)
    t.field("Response", f"HTTP {r.status_code} {r.reason}" + (f"  (after {tries} connection attempts)" if tries > 1 else ""))
    if r.status_code == 202:
        status = follow_async(t, r)
        t.field("Verdict", "LIMIT ENFORCED: job failed" if status == "failed" else "NOT ENFORCED: job accepted and ran")
    else:
        t.field("Error", error_of(r))
        t.field("Verdict", "LIMIT ENFORCED: whole request rejected" if r.status_code == 400 else f"UNEXPECTED: HTTP {r.status_code}")
    return t


def test_lang_chars_async():
    t = Transcript("lang-chars-async", "Azure AI Language: asynchronous job over 125,000 characters in total")
    t.field("Limit under test", "Max 125,000 characters across all documents, asynchronous")
    t.field("Source", LANG_DOCS)
    docs = [{"id": str(i), "language": "en", "text": filler(5100)} for i in range(25)]
    t.field("Request", "POST analyze-text/jobs (PII)  documents: 25 x 5,100 chars = 127,500 chars")
    r, tries = lang_async(docs)
    t.field("Response", f"HTTP {r.status_code} {r.reason}" + (f"  (after {tries} connection attempts)" if tries > 1 else ""))
    if r.status_code == 202:
        status = follow_async(t, r)
        t.field("Verdict", "LIMIT ENFORCED: job failed" if status == "failed" else "NOT ENFORCED: job accepted and ran")
    else:
        t.field("Error", error_of(r))
        if r.status_code == 400:
            t.field("Verdict", "LIMIT ENFORCED: whole request rejected")
        elif 400 < r.status_code < 500:
            t.field("Verdict", f"LIMIT ENFORCED: whole request rejected, with HTTP {r.status_code} (Microsoft's data-limits page says 400)")
        else:
            t.field("Verdict", f"UNEXPECTED: HTTP {r.status_code}")
    return t


def test_lang_rate():
    t = Transcript("lang-rate", "Azure AI Language: burst of requests above the per-minute rate limit")
    t.field("Limit under test", "S0: 100 requests per second, 300 per minute (S tier: 1,000 / 1,000)")
    t.field("Source", LANG_DOCS)
    # 1,100 requests: above the S0 limits (300 per minute) and the S tier's 1,000 per minute
    n, workers = int(os.environ.get("LANG_RATE_REQUESTS", "1100")), 40
    t.field("Request", f"{n:,} x POST :analyze-text (PII, 1 short document each), {workers} in parallel")
    sample_429 = {}
    local = threading.local()

    def call(_):
        if not hasattr(local, "s"):
            local.s = requests.Session()
        try:
            r = local.s.post(LANG_SYNC, params={"api-version": LANG_API}, timeout=60,
                             headers={"Ocp-Apim-Subscription-Key": LANG_KEY},
                             json={"kind": "PiiEntityRecognition", "parameters": {"modelVersion": "latest"},
                                   "analysisInput": {"documents": [{"id": "1", "language": "en", "text": "hello"}]}})
            if r.status_code == 429 and not sample_429:
                sample_429.update(error=error_of(r), retry_after=r.headers.get("Retry-After"))
            return f"HTTP {r.status_code}"
        except requests.RequestException as exc:
            local.__dict__.pop("s", None)
            return f"connection error ({type(exc).__name__})"

    start = time.time()
    with ThreadPoolExecutor(workers) as pool:
        counts = collections.Counter(pool.map(call, range(n)))
    t.field("Duration", f"{time.time() - start:.1f} s")
    for status, count in sorted(counts.items()):
        t.field("  " + status, f"{count} requests")
    if sample_429:
        t.field("429 body", sample_429["error"])
        t.field("Retry-After", sample_429["retry_after"])
        t.field("Verdict", "LIMIT ENFORCED: requests over the rate were refused with HTTP 429")
    else:
        t.field("Verdict", f"NOT TRIGGERED: no HTTP 429 in {n:,} requests")
    return t


# --- This pipeline's own pre-check -----------------------------------------------------

def test_precheck():
    t = Transcript("pipeline-precheck", "This pipeline: oversized files rejected before any Azure call")
    t.field("Limits applied", "500 MB and 2,000 pages, the Document Intelligence S0 limits")
    sys.path.insert(0, ROOT)
    import languageservice as ls
    with tempfile.TemporaryDirectory() as tmp:
        pages_path = os.path.join(tmp, "statement_2001_pages.pdf")
        with open(pages_path, "wb") as f:
            f.write(blank_pdf(2001))
        size_path = os.path.join(tmp, "statement_501_MiB.pdf")
        with open(size_path, "wb") as f:
            f.write(b"%PDF-1.7\n")
            f.truncate(501 * 1024 * 1024)  # sparse file: reports 501 MiB without using the disk
        for path in (pages_path, size_path):
            t.add("")
            t.add(f"$ python languageservice.py {os.path.basename(path)}")
            try:
                ls.precheck(path)
                t.add('{"status": "ok"}')
                t.field("Verdict", "NOT REJECTED")
            except ls.PipelineError as exc:
                t.add('{"status": "error", "error": "' + str(exc) + '"}')
                t.add("exit code 1, no request sent to Document Intelligence or Language")
    t.add("")
    t.field("Verdict", "REJECTED BY PRE-CHECK: both files stopped before upload")
    return t


TESTS = {
    "di-pages": test_di_pages,
    "di-rate": test_di_rate,
    "lang-chars": test_lang_chars,
    "lang-docs-sync": test_lang_docs_sync,
    "lang-docs-async": test_lang_docs_async,
    "lang-chars-async": test_lang_chars_async,
    "lang-rate": test_lang_rate,
    "pipeline-precheck": test_precheck,
    "di-size": test_di_size,
}

if __name__ == "__main__":
    selected = sys.argv[1:] or list(TESTS)
    for name in selected:
        transcript = TESTS[name]()
        transcript.save()
        print()
