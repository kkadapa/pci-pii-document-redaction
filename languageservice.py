"""
PCI/PII redaction pipeline:
  1. Azure AI Document Intelligence (prebuilt-read) extracts text from the document.
  2. Azure AI Language PII detection (REST API) finds sensitive values. Requests run in
     parallel over overlapping chunks, with an explicit category list that includes the
     preview CVV and ExpirationDate categories.
  3. A deterministic rule layer (Luhn-checked card numbers, label-anchored CVV and expiry
     values) masks anything the Language service missed.
  4. The masked output is checked before returning. If a card number or CVV survives, or
     any step fails, the whole document fails. No partial output is returned.

The response contains masked text and entity metadata only. Raw values are never
returned or logged.

Required .env variables:
  AZURE_DOCINTEL_ENDPOINT, AZURE_DOCINTEL_KEY
  AZURE_LANGUAGE_ENDPOINT, AZURE_LANGUAGE_KEY

Usage:
  python languageservice.py path/to/document.pdf
"""

import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import requests
from dotenv import load_dotenv
from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import HttpResponseError
from azure.ai.documentintelligence import DocumentIntelligenceClient

load_dotenv()

# --- Limits (see README "Service limits") ---------------------------------------------
MAX_FILE_BYTES = 500 * 1024 * 1024   # Document Intelligence S0 max document size
MAX_CHARS_PER_DOC = 5000             # Language sync limit is 5,120 text elements
CHUNK_OVERLAP = 100                  # so values cut at a chunk boundary are still seen whole
MAX_DOCS_PER_REQUEST = 5             # Language sync limit for PII
PARALLEL_REQUESTS = 5                # bounded concurrency for Language calls
MAX_RETRIES = 5                      # for HTTP 429 / 5xx

# --- Language API configuration -------------------------------------------------------
# Preview version is required for the CVV and ExpirationDate categories.
LANGUAGE_API_VERSION = "2026-05-15-preview"
PII_CATEGORIES = [
    # Payment card
    "CreditCardNumber", "CVV", "ExpirationDate",
    # Bank and tax identifiers
    "USBankAccountNumber", "BankAccountNumber", "ABARoutingNumber", "SWIFTCode",
    "InternationalBankingAccountNumber", "USSocialSecurityNumber",
    "USIndividualTaxpayerIdentification",
    # Personal
    "Person", "Email", "PhoneNumber", "Address", "DateOfBirth",
]

# --- Deterministic rules ----------------------------------------------------------------
# 13-19 digits, optionally separated by single spaces or dashes. Validated with Luhn.
PAN_PATTERN = re.compile(r"(?<![\d*])\d(?:[ -]?\d){12,18}(?![\d*])")
CVV_PATTERN = re.compile(
    r"\b(?:CVV2?|CVC2?|CID|CSC|Security\s+code)\b\s*[:#]?\s*(\d{3,4})\b", re.IGNORECASE
)
EXPIRY_PATTERN = re.compile(
    r"\b(?:Exp(?:iry|iration)?(?:\s+date)?|Valid\s+thru)\b\.?\s*[:#]?\s*"
    r"((?:0?[1-9]|1[0-2])\s*/\s*(?:\d{4}|\d{2}))(?!\d)",
    re.IGNORECASE,
)


class PipelineError(Exception):
    """Raised when the document cannot be safely masked. Never contains document text."""


def _require_env(name):
    value = os.environ.get(name, "").strip()
    if not value:
        raise PipelineError(f"Missing environment variable: {name}")
    return value


# --- Step 1: Document Intelligence -------------------------------------------------------

def get_document_client():
    return DocumentIntelligenceClient(
        endpoint=_require_env("AZURE_DOCINTEL_ENDPOINT"),
        credential=AzureKeyCredential(_require_env("AZURE_DOCINTEL_KEY")),
    )


def extract_text(doc_client, file_bytes):
    """Run OCR and return (full text, page count)."""
    result = doc_client.begin_analyze_document(
        "prebuilt-read", body=file_bytes, content_type="application/octet-stream"
    ).result()
    return result.content or "", len(result.pages or [])


# --- Step 2: Language PII detection ------------------------------------------------------

def split_text(text, max_chars=MAX_CHARS_PER_DOC, overlap=CHUNK_OVERLAP):
    """
    Split text into (start_offset, chunk) pairs of at most max_chars, preferring to end
    at a line break. Consecutive chunks overlap by `overlap` characters.
    """
    chunks, start, n = [], 0, len(text)
    while start < n:
        end = min(start + max_chars, n)
        if end < n:
            newline = text.rfind("\n", start + max_chars // 2, end)
            if newline != -1:
                end = newline + 1
        chunks.append((start, text[start:end]))
        if end >= n:
            break
        start = max(end - overlap, start + 1)
    return chunks


def _post_language(endpoint, key, documents):
    """POST one batch to the Language API, retrying 429 and 5xx. Raises on any failure."""
    body = {
        "kind": "PiiEntityRecognition",
        "analysisInput": {"documents": documents},
        "parameters": {
            "modelVersion": "latest",
            "piiCategories": PII_CATEGORIES,
            "stringIndexType": "UnicodeCodePoint",  # offsets match Python string indices
        },
    }
    for attempt in range(MAX_RETRIES):
        try:
            response = requests.post(
                f"{endpoint}/language/:analyze-text",
                params={"api-version": LANGUAGE_API_VERSION},
                headers={"Ocp-Apim-Subscription-Key": key},
                json=body,
                timeout=60,
            )
        except requests.RequestException as exc:
            if attempt == MAX_RETRIES - 1:
                raise PipelineError(f"Language request failed: {type(exc).__name__}") from None
            time.sleep(2 ** attempt)
            continue

        if response.status_code == 200:
            results = response.json()["results"]
            if results.get("errors"):
                codes = [e.get("error", {}).get("code", "unknown") for e in results["errors"]]
                raise PipelineError(f"Language returned document errors: {codes}")
            return results
        if response.status_code == 429 or response.status_code >= 500:
            wait = float(response.headers.get("Retry-After", 2 ** attempt))
            time.sleep(wait)
            continue
        raise PipelineError(f"Language request failed with HTTP {response.status_code}")

    raise PipelineError("Language request failed after retries")


def detect_with_language(text, workers=PARALLEL_REQUESTS):
    """Return (entities with absolute offsets, model version). Entity text is dropped."""
    endpoint = _require_env("AZURE_LANGUAGE_ENDPOINT").rstrip("/")
    key = _require_env("AZURE_LANGUAGE_KEY")

    chunks = split_text(text)
    batches = [chunks[i:i + MAX_DOCS_PER_REQUEST] for i in range(0, len(chunks), MAX_DOCS_PER_REQUEST)]

    def run(batch):
        docs = [{"id": str(start), "language": "en", "text": chunk} for start, chunk in batch]
        return _post_language(endpoint, key, docs)

    entities, seen, model_versions = [], set(), set()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for results in pool.map(run, batches):
            model_versions.add(results.get("modelVersion", "unknown"))
            for doc in results["documents"]:
                base = int(doc["id"])
                for e in doc["entities"]:
                    span = (base + e["offset"], e["length"], e["category"])
                    if span in seen:  # same entity found in two overlapping chunks
                        continue
                    seen.add(span)
                    entities.append({
                        "category": e["category"],
                        "source": "language",
                        "confidence_score": round(e.get("confidenceScore", 0.0), 3),
                        "offset": span[0],
                        "length": span[1],
                    })
    return entities, sorted(model_versions)


# --- Step 3: Deterministic rules ---------------------------------------------------------

def luhn_valid(digits):
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def find_card_numbers(text):
    """Yield (offset, length) of Luhn-valid 13-19 digit sequences."""
    for m in PAN_PATTERN.finditer(text):
        digits = re.sub(r"\D", "", m.group())
        if 13 <= len(digits) <= 19 and luhn_valid(digits):
            yield m.start(), m.end() - m.start()


def detect_with_rules(text):
    entities = []
    for offset, length in find_card_numbers(text):
        entities.append({"category": "CreditCardNumber", "source": "rule", "offset": offset, "length": length})
    for pattern, category in ((CVV_PATTERN, "CVV"), (EXPIRY_PATTERN, "ExpirationDate")):
        for m in pattern.finditer(text):
            entities.append({"category": category, "source": "rule", "offset": m.start(1), "length": m.end(1) - m.start(1)})
    return entities


# --- Step 4: Mask and validate -----------------------------------------------------------

def merge_and_mask(text, language_entities, rule_entities):
    """
    Mask every span found by either layer. Rule matches already covered by a Language
    entity are not listed twice. Returns (masked_text, entities).
    """
    covered = [(e["offset"], e["offset"] + e["length"]) for e in language_entities]

    def is_covered(e):
        return any(s <= e["offset"] and e["offset"] + e["length"] <= t for s, t in covered)

    entities = language_entities + [e for e in rule_entities if not is_covered(e)]
    entities.sort(key=lambda e: (e["offset"], e["length"]))

    chars = list(text)
    for e in entities:
        for i in range(e["offset"], e["offset"] + e["length"]):
            chars[i] = "*"
        e["masked_value"] = "*" * e["length"]
    return "".join(chars), entities


def validate_masked(masked_text):
    """Fail closed if any card number or labeled CVV survives masking."""
    if any(True for _ in find_card_numbers(masked_text)):
        raise PipelineError("Validation failed: a card number survived masking")
    if CVV_PATTERN.search(masked_text):
        raise PipelineError("Validation failed: a CVV survived masking")


# --- Pipeline ----------------------------------------------------------------------------

def process_document(file_path):
    """Run the full pipeline on a local file and return a JSON-serializable dict."""
    size = os.path.getsize(file_path)
    if size > MAX_FILE_BYTES:
        raise PipelineError(f"File is {size} bytes; the Document Intelligence limit is {MAX_FILE_BYTES}")

    with open(file_path, "rb") as f:
        file_bytes = f.read()

    timings = {}
    t0 = time.perf_counter()
    text, pages = extract_text(get_document_client(), file_bytes)
    timings["document_intelligence_s"] = round(time.perf_counter() - t0, 1)

    if not text.strip():
        return {"status": "no_text", "source_file": os.path.basename(file_path), "pages": pages}

    t0 = time.perf_counter()
    language_entities, model_versions = detect_with_language(text)
    timings["language_s"] = round(time.perf_counter() - t0, 1)

    rule_entities = detect_with_rules(text)
    masked_text, entities = merge_and_mask(text, language_entities, rule_entities)
    validate_masked(masked_text)

    counts = {}
    for e in entities:
        counts[e["category"]] = counts.get(e["category"], 0) + 1

    return {
        "status": "ok",
        "source_file": os.path.basename(file_path),
        "pages": pages,
        "characters": len(text),
        "language_api_version": LANGUAGE_API_VERSION,
        "language_model_versions": model_versions,
        "timings": timings,
        "pii_detected": bool(entities),
        "category_counts": dict(sorted(counts.items())),
        "rule_only_detections": sum(1 for e in entities if e["source"] == "rule"),
        "entity_count": len(entities),
        "entities": entities,
        "masked_text": masked_text,
    }


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python languageservice.py <document path>", file=sys.stderr)
        sys.exit(2)
    try:
        output = process_document(sys.argv[1])
    except PipelineError as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, indent=2))
        sys.exit(1)
    except HttpResponseError as exc:  # Document Intelligence errors (auth, size, format)
        print(json.dumps({"status": "error", "error": f"Document Intelligence HTTP {exc.status_code}: {exc.reason}"}, indent=2))
        sys.exit(1)
    print(json.dumps(output, indent=2))
