"""
PCI/PII pipeline:
  1. Azure Document Intelligence (prebuilt-read) extracts text from an uploaded document.
  2. Azure AI Language (PII detection) flags sensitive data and returns a masked version.
  3. A JSON response is returned containing the masked text and entity metadata only.
     Raw card/PII values are never included in the response or logged.

Required .env variables:
  AZURE_DOCINTEL_ENDPOINT   https://idpgtadoc.cognitiveservices.azure.com/
  AZURE_DOCINTEL_KEY        key for the Document Intelligence resource
  AZURE_LANGUAGE_ENDPOINT   https://gta6langservice.cognitiveservices.azure.com/
  AZURE_LANGUAGE_KEY        key for the Language resource

Usage:
  python languageservice.py path/to/document.pdf
"""

import json
import os
import sys

from dotenv import load_dotenv
from azure.core.credentials import AzureKeyCredential
from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.ai.textanalytics import TextAnalyticsClient

load_dotenv()

# Language PII API accepts up to 5,120 characters per document.
MAX_CHARS_PER_DOC = 5000
# Language API accepts up to 5 documents per request in the batch call.
MAX_DOCS_PER_REQUEST = 5


def _require_env(name):
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing environment variable: {name}")
    return value


def get_document_client():
    return DocumentIntelligenceClient(
        endpoint=_require_env("AZURE_DOCINTEL_ENDPOINT"),
        credential=AzureKeyCredential(_require_env("AZURE_DOCINTEL_KEY")),
    )


def get_language_client():
    return TextAnalyticsClient(
        endpoint=_require_env("AZURE_LANGUAGE_ENDPOINT"),
        credential=AzureKeyCredential(_require_env("AZURE_LANGUAGE_KEY")),
    )


def extract_text(doc_client, file_bytes):
    """Run Document Intelligence OCR on the document and return its full text."""
    poller = doc_client.begin_analyze_document(
        "prebuilt-read",
        body=file_bytes,
        content_type="application/octet-stream",
    )
    result = poller.result()
    return result.content or ""


def split_text(text, max_chars=MAX_CHARS_PER_DOC):
    """Split text into chunks under the Language size limit, preferring line breaks."""
    chunks, current = [], ""
    for line in text.splitlines(keepends=True):
        while len(line) > max_chars:  # hard-split any single line that is too long
            if current:
                chunks.append(current)
                current = ""
            chunks.append(line[:max_chars])
            line = line[max_chars:]
        if len(current) + len(line) > max_chars:
            chunks.append(current)
            current = ""
        current += line
    if current:
        chunks.append(current)
    return chunks


def detect_and_mask_pii(lang_client, text):
    """Detect PII/PCI in text and return (masked_text, entities)."""
    chunks = split_text(text)
    masked_parts, entities = [], []
    offset_base = 0

    for start in range(0, len(chunks), MAX_DOCS_PER_REQUEST):
        batch = chunks[start:start + MAX_DOCS_PER_REQUEST]
        responses = lang_client.recognize_pii_entities(batch, language="en")
        for chunk, doc in zip(batch, responses):
            if doc.is_error:
                raise RuntimeError(f"Language service error: {doc.error.message}")
            masked_parts.append(doc.redacted_text)
            for entity in doc.entities:
                entities.append({
                    "category": entity.category,
                    "subcategory": entity.subcategory,
                    "confidence_score": round(entity.confidence_score, 3),
                    # Offsets are into the full extracted text, so a caller can locate the span.
                    "offset": offset_base + entity.offset,
                    "length": entity.length,
                    "masked_value": "*" * entity.length,
                })
            offset_base += len(chunk)

    return "".join(masked_parts), entities


def process_document(file_path):
    """Run the full pipeline on a local file and return a JSON-serializable dict."""
    with open(file_path, "rb") as f:
        file_bytes = f.read()

    doc_client = get_document_client()
    lang_client = get_language_client()

    text = extract_text(doc_client, file_bytes)
    if not text.strip():
        return {"status": "no_text", "source_file": os.path.basename(file_path)}

    masked_text, entities = detect_and_mask_pii(lang_client, text)
    categories = sorted({e["category"] for e in entities})

    return {
        "status": "ok",
        "source_file": os.path.basename(file_path),
        "pii_detected": bool(entities),
        "categories": categories,
        "entity_count": len(entities),
        "entities": entities,
        "masked_text": masked_text,
    }


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python languageservice.py <document path>", file=sys.stderr)
        sys.exit(2)
    print(json.dumps(process_document(sys.argv[1]), indent=2))
