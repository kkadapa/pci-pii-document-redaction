# PCI/PII Document Redaction (Azure Document Intelligence + Azure AI Language)

Upload a document that contains payment card (PCI) or personal (PII) data. The pipeline extracts the text, detects sensitive values, masks them, and returns JSON that contains only the masked text and entity metadata. Raw card numbers and CVVs are never returned or logged.

Written for: developers setting up this project for the first time.

## Architecture

```
PDF / image upload
        |
        v
Azure AI Document Intelligence  (prebuilt-read)   resource: idpgtadoc
        |  extracted text
        v
Azure AI Language (PII detection)                 resource: gta6langservice
        |  detected entities + redacted text
        v
JSON response: masked_text, categories, entities (offsets, masked_value)
```

| Step | Azure service | What it does |
|------|---------------|--------------|
| 1. OCR | Document Intelligence, `prebuilt-read` | Extracts all text from the document, including scanned pages |
| 2. Detect and mask | Azure AI Language, PII detection | Finds card numbers, CVVs, names, emails, phone numbers, etc., and returns `redacted_text` with those spans masked |
| 3. Respond | `languageservice.py` | Returns JSON. Does not include the original sensitive values |

## Project files

| File | Purpose |
|------|---------|
| `languageservice.py` | The pipeline. Run it on a file or import `process_document(path)` |
| `sample_pci_test.pdf` | Test form with public test card numbers (Visa `4111 1111 1111 1111`, Mastercard `5555 5555 5555 4444`) and sample CVVs. Not real accounts |
| `.env` | Secrets and endpoints. Not committed (see `.gitignore`) |
| `.gitignore` | Excludes `.env`, `.venv/`, `__pycache__/`, `.vscode/` |

## Setup

1. Create a `.env` file in the project root:

   ```
   AZURE_DOCINTEL_ENDPOINT=https://idpgtadoc.cognitiveservices.azure.com/
   AZURE_DOCINTEL_KEY=<Document Intelligence key1>
   AZURE_LANGUAGE_ENDPOINT=https://gta6langservice.cognitiveservices.azure.com/
   AZURE_LANGUAGE_KEY=<Language key1>
   ```

2. Install dependencies:

   ```
   pip install python-dotenv azure-core azure-ai-textanalytics azure-ai-documentintelligence
   ```

3. Run:

   ```
   python languageservice.py sample_pci_test.pdf
   ```

   If a variable is missing, the script stops with `Missing environment variable: <NAME>`.

## Output

```json
{
  "status": "ok",
  "source_file": "sample_pci_test.pdf",
  "pii_detected": true,
  "categories": ["CreditCardNumber", "Email", "PhoneNumber", "..."],
  "entity_count": 0,
  "entities": [
    {
      "category": "CreditCardNumber",
      "subcategory": null,
      "confidence_score": 0.85,
      "offset": 120,
      "length": 19,
      "masked_value": "*******************"
    }
  ],
  "masked_text": "...Card Number: ******************* ..."
}
```

`status` is `no_text` if Document Intelligence finds no text in the file.

## Service limits

Limits come from Microsoft's documentation and change over time. Re-check the linked pages before you design anything around them.

### Document Intelligence (Read model, `prebuilt-read`)

| Limit | Value | Status |
|-------|-------|--------|
| File size per document, S0 (paid) | 500 MB | Verified. [Service quotas and limits](https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/service-limits) |
| File size per document, F0 (free) | 4 MB | Verified. Same source |
| Pages per document, S0 | 2,000 | Verified. Same source |
| Pages per document, F0 | 2 | Verified. Same source |
| Analyze requests per second, S0 | 15 by default (adjustable on request) | Verified. Same source |
| Analyze requests per second, F0 | 1 | Verified. Same source |
| OCR JSON response size | 500 MB | Verified. Same source |

### Azure AI Language (PII detection)

| Limit | Value | Status |
|-------|-------|--------|
| Documents per request, synchronous API | 5 | Verified. [Data limits](https://learn.microsoft.com/en-us/azure/ai-services/language-service/concepts/data-limits) |
| Documents per request, asynchronous API | 25 | Verified. Same source |
| Characters per document | 5,120 | **Unverified.** Written from memory, not confirmed by the sources I checked. Confirm on the data limits page before relying on it. The code uses this value as its chunk size |
| Pricing unit | 1 text record = 1,000 characters | Verified. Billing measure, not a cap. Same source |

The code in `languageservice.py` uses `MAX_CHARS_PER_DOC = 5000` and `MAX_DOCS_PER_REQUEST = 5`. Those values stay under the limits above. If the 5,120 figure is confirmed, the chunk size can go up slightly.

## Scaling to large documents (500 pages and beyond)

**Example:** A 500-page document is under the S0 limits (2,000 pages, 500 MB), so a single Document Intelligence call works. The Language side is the bottleneck. 500 pages of text can be roughly 500,000 to 1,000,000 characters. At 5,000 characters per document and 5 documents per request, that is about 100 to 200 documents, or 20 to 40 synchronous requests. Those requests run one after another in the current code, which is slow.

Recommendations for an enterprise deployment:

1. **Keep Document Intelligence on whole files up to 2,000 pages.** Split only when a file goes over the limit. The `pages` parameter on `begin_analyze_document` (for example `"1-100"`) can process page ranges.
2. **Use the asynchronous Language API for batches.** It accepts up to 25 documents per request. Submit batches in parallel, with a bounded concurrency setting.
3. **Handle throttling.** Retry on HTTP 429 with exponential backoff. Watch the 15 requests-per-second default for Document Intelligence.
4. **Process in a queue, not in a request.** A 500-page file takes time to analyze. Upload to Blob Storage, queue a job (Azure Functions or Service Bus), and return a job ID. The caller polls for the masked JSON.
5. **Check file size before upload.** Reject files over 500 MB and files over 2,000 pages up front. Those are hard service limits.
6. **Secure the pipeline.** Use Key Vault or managed identity instead of keys in `.env`. Use private endpoints for both resources. Do not log extracted text or entity values. Set a retention policy for uploaded files and intermediate text.
7. **Test with production-like documents.** Measure throughput and cost on a sample of real documents before sizing the deployment.

## Known limitations

- Masking replaces the whole entity with asterisks. The last four digits are not kept. This can be changed.
- Detection is probabilistic. Use `confidence_score` and a human review step for high-risk documents.
- The Language service's PII categories and its accuracy for CVVs and expiration dates should be tested on your own documents.
