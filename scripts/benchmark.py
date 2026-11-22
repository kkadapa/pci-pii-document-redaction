"""
Times each pipeline stage on a document:
  1. Document Intelligence (prebuilt-read) text extraction
  2. Language PII detection with 1 worker (sequential)
  3. Language PII detection with N parallel workers (the pipeline default is 5)

Prints timings and sizes only. No extracted text or PII values are printed.

Usage (from the project root):
  python scripts/benchmark.py <document path> [parallel_workers]
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import languageservice as ls  # noqa: E402


def main(path, workers):
    with open(path, "rb") as f:
        data = f.read()

    t0 = time.perf_counter()
    text, pages = ls.extract_text(ls.get_document_client(), data)
    t_di = time.perf_counter() - t0

    chunks = ls.split_text(text)
    requests_needed = -(-len(chunks) // ls.MAX_DOCS_PER_REQUEST)

    t0 = time.perf_counter()
    seq_entities, _ = ls.detect_with_language(text, workers=1)
    t_seq = time.perf_counter() - t0

    t0 = time.perf_counter()
    par_entities, _ = ls.detect_with_language(text, workers=workers)
    t_par = time.perf_counter() - t0

    t0 = time.perf_counter()
    rules = ls.detect_with_rules(text)
    masked, _ = ls.merge_and_mask(text, par_entities, rules)
    ls.validate_masked(masked)
    t_rules = time.perf_counter() - t0

    print(f"file: {os.path.basename(path)}  size: {len(data) / 1024:.0f} KB  pages: {pages}")
    print(f"extracted characters: {len(text):,}  chunks: {len(chunks)}  language requests: {requests_needed}")
    print(f"document intelligence:        {t_di:6.1f} s  ({t_di / max(pages, 1) * 1000:.0f} ms/page)")
    print(f"language, 1 worker:           {t_seq:6.1f} s  entities: {len(seq_entities)}")
    print(f"language, {workers} workers:          {t_par:6.1f} s  entities: {len(par_entities)}")
    print(f"rules + mask + validate:      {t_rules:6.2f} s")
    print(f"end to end, 1 worker:         {t_di + t_seq + t_rules:6.1f} s")
    print(f"end to end, {workers} workers:        {t_di + t_par + t_rules:6.1f} s")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/benchmark.py <document path> [parallel_workers]", file=sys.stderr)
        sys.exit(2)
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else ls.PARALLEL_REQUESTS)
