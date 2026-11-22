"""
Tests the size and page-count pre-check offline. No Azure calls are made.

Generates edge-case files in a temporary folder (blank-page PDFs at and over the
2,000-page limit, multi-frame TIFFs, a PNG, a damaged PDF, a text file), runs
languageservice.precheck() on each, and on the 500-page statement if it exists.

Usage (from the project root):
  python scripts/test_precheck.py
"""

import os
import sys
import tempfile
import time

from PIL import Image
from pypdf import PdfWriter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import languageservice as ls  # noqa: E402


def blank_pdf(path, pages):
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(612, 792)
    writer.write(path)


def tiff(path, frames):
    images = [Image.new("1", (8, 8)) for _ in range(frames)]
    images[0].save(path, save_all=True, append_images=images[1:])


def main():
    with tempfile.TemporaryDirectory() as tmp:
        cases = [("sample_pci_test.pdf", "1-page form", "pass")]
        for pages in (500, 2000):
            path = f"test_data/banking_statements_{pages}p.pdf"
            if os.path.exists(path):
                cases.append((path, f"{pages:,}-page bank statement", "pass"))

        generated = [
            ("p2000.pdf", "PDF, 2,000 blank pages", "pass", lambda p: blank_pdf(p, 2000)),
            ("p2001.pdf", "PDF, 2,001 blank pages", "reject", lambda p: blank_pdf(p, 2001)),
            ("f3.tiff", "TIFF, 3 frames", "pass", lambda p: tiff(p, 3)),
            ("f2001.tiff", "TIFF, 2,001 frames", "reject", lambda p: tiff(p, 2001)),
            ("one.png", "PNG image", "pass", lambda p: Image.new("RGB", (10, 10)).save(p)),
            ("broken.pdf", "Damaged PDF", "pass", lambda p: open(p, "wb").write(b"%PDF-1.7\nnot a pdf")),
            ("notes.txt", "Text file", "pass", lambda p: open(p, "wb").write(b"hello")),
        ]
        for name, label, expected, make in generated:
            path = os.path.join(tmp, name)
            make(path)
            cases.append((path, label, expected))

        failures = 0
        print(f"{'File':26s} {'Size':>9s} {'Type':6s} {'Pages':>6s} {'Result':8s} {'Time':>7s}")
        for path, label, expected in cases:
            size = os.path.getsize(path)
            t0 = time.perf_counter()
            try:
                info = ls.precheck(path)
                ms = (time.perf_counter() - t0) * 1000
                result, pages, ftype = "pass", info["pages_counted"], info["file_type"]
            except ls.PipelineError:
                ms = (time.perf_counter() - t0) * 1000
                result, (ftype, pages) = "reject", ls.count_pages(path)  # for display only
            ok = result == expected
            failures += not ok
            pages_s = "n/a" if pages is None else f"{pages:,}"
            print(f"{label:26s} {size / 1024:7.0f} KB {ftype:6s} {pages_s:>6s} {result:8s} {ms:5.0f} ms"
                  f"{'' if ok else '  <-- UNEXPECTED'}")

    print("\nAll cases behaved as expected." if not failures else f"\n{failures} unexpected result(s).")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
