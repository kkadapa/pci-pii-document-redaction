# PCI/PII Document Redaction with Azure Document Intelligence and Azure AI Language

This project takes an uploaded document that contains payment card (PCI) or personal (PII) data and returns JSON with the sensitive values masked. Two Azure services do the work:

1. **Azure AI Document Intelligence** reads the document (including scanned pages) and extracts the text.
2. **Azure AI Language** (PII detection) finds sensitive values in that text.

A deterministic rule layer then catches card numbers, CVVs, and expiry dates the Language service misses. A final check blocks the response if any card number or CVV survives masking.

The response contains only masked text and entity metadata (category, position, length, confidence). The original sensitive values are never returned or logged.

> **Status: prototype.** On a 500-page synthetic bank statement, every planted card number, CVV, expiry date, email, phone number, and name was masked, and processing took 40.8 seconds end to end. CVV and expiry detection rely on Language API *preview* features. Read [Known gaps](#known-gaps) and [Enterprise approach](#enterprise-approach-for-financial-institutions) before using this with real card data.

## Contents

- [Target-state architecture](#target-state-architecture)
- [How the pipeline works](#how-the-pipeline-works)
- [Project files](#project-files)
- [Setup and usage](#setup-and-usage)
- [Service limits](#service-limits)
- [Test results](#test-results)
- [Known gaps](#known-gaps)
- [Enterprise approach for financial institutions](#enterprise-approach-for-financial-institutions)
- [File size and page recommendations](#file-size-and-page-recommendations)

## Target-state architecture

![Target-state architecture diagram](docs/architecture.svg)

[docs/architecture.md](docs/architecture.md) walks through all 13 steps, with a sequence diagram, a time budget for a 500-page document, and what happens when each step fails. The size and page checks from step 2, and steps 6 to 10, are implemented in `languageservice.py`. The other steps are the production design.

## How the pipeline works

```
PDF / image upload
        |
        v
0. Pre-check, before any Azure call
   - size from file metadata: reject if over 500 MB
   - pages counted inside the file: reject if over 2,000
     (PDF page list, TIFF frames, single images = 1)
        |
        v
1. Azure AI Document Intelligence (prebuilt-read)                  resource: idpgtadoc
        |  extracted text
        v
2. Split into chunks of up to 5,000 characters, ending at line breaks,
   with 100 characters of overlap between chunks
        |
        v
3. Azure AI Language PII detection, REST API 2026-05-15-preview      resource: gta6langservice
   - explicit category list, including CVV and ExpirationDate
   - 5 chunks per request, 5 requests in parallel
   - retries on HTTP 429 and 5xx (up to 5 attempts), honoring Retry-After
        |
        v
4. Rule layer over the full text
   - 13-19 digit numbers that pass the Luhn check (card numbers)
   - 3-4 digits after CVV / CVC / CVV2 / CID / CSC / Security code
   - month/year after Exp / Expiry / Expiration / Valid thru
        |
        v
5. Mask the union of all detected spans with *
        |
        v
6. Validate: if any Luhn-valid card number or labeled CVV remains, fail
        |
        v
JSON response
```

The pre-check detects the file type from the file's first bytes, not its extension. If it can't determine the page count, it lets the file through rather than guessing. That covers encrypted or damaged PDFs and Office files. Document Intelligence then enforces its own limit. Details: [How the size and page checks work](docs/architecture.md#how-the-size-and-page-checks-work).

The pipeline **fails closed**. If any Language request fails, any chunk returns an error, or the final check finds a surviving card number or CVV, it returns `{"status": "error"}` and no text at all. The error message never includes document content.

### Categories requested

| Group | Categories |
|-------|------------|
| Payment card | `CreditCardNumber`, `CVV` (preview), `ExpirationDate` (preview) |
| Bank and tax | `USBankAccountNumber`, `BankAccountNumber` (preview), `ABARoutingNumber`, `SWIFTCode`, `InternationalBankingAccountNumber`, `USSocialSecurityNumber`, `USIndividualTaxpayerIdentification` |
| Personal | `Person`, `Email`, `PhoneNumber`, `Address`, `DateOfBirth` (preview) |

To change the list, edit `PII_CATEGORIES` in `languageservice.py`.

General categories such as `Organization` and `DateTime` are left out on purpose. On transaction-heavy documents they mask merchant names and every transaction date, which buries the sensitive values. The service sometimes still labels an expiry date as `DateTime`; that entity is masked like any other.

### Why the REST API instead of the SDK

The `azure-ai-textanalytics` SDK (5.4.0, the latest release) supports Language API versions up to `2023-04-01`. That version has no `CVV` or `ExpirationDate` category. The pipeline calls the REST API directly so it can use `2026-05-15-preview`.

## Project files

| File | Purpose |
|------|---------|
| `languageservice.py` | The pipeline. Run it on a file, or import `process_document(path)` |
| `scripts/generate_banking_pdf.py` | Generates a synthetic 500-page bank statement PDF and a ground-truth file listing every planted value |
| `scripts/score_results.py` | Scores pipeline output against the ground truth |
| `scripts/benchmark.py` | Times each stage, and compares 1 worker with N parallel workers for Language calls |
| `scripts/probe_pii_categories.py` | Calls the Language REST API to compare what each API version detects |
| `scripts/render_architecture.py` | Generates `docs/architecture.svg` |
| `docs/architecture.md` | Target-state architecture and end-to-end flow |
| `sample_pci_test.pdf` | One-page test form with public test card numbers and sample CVVs. Not real accounts |
| `requirements.txt` | Pinned dependencies |
| `test_data/` | Generated test files and results. Not committed |
| `.env` | Endpoints and keys. Not committed |

## Setup and usage

1. Create `.env` in the project root:

   ```
   AZURE_DOCINTEL_ENDPOINT=https://idpgtadoc.cognitiveservices.azure.com/
   AZURE_DOCINTEL_KEY=<Document Intelligence key>
   AZURE_LANGUAGE_ENDPOINT=https://gta6langservice.cognitiveservices.azure.com/
   AZURE_LANGUAGE_KEY=<Language key>
   ```

   Each key must belong to the resource at the matching endpoint. A Document Intelligence key does not work against the Language API. The mismatch returns `401 Access denied due to invalid subscription key or wrong API endpoint`.

2. Install dependencies:

   ```
   pip install -r requirements.txt
   ```

3. Run the pipeline:

   ```
   python languageservice.py sample_pci_test.pdf
   ```

   The exit code is 0 on success and 1 on a pipeline error.

4. Optional: reproduce the 500-page test:

   ```
   python scripts/generate_banking_pdf.py
   python languageservice.py test_data/banking_statements_500p.pdf > test_data/results.json
   python scripts/score_results.py test_data/results.json
   python scripts/benchmark.py test_data/banking_statements_500p.pdf
   ```

### Example output (`sample_pci_test.pdf`, entities shortened)

```json
{
  "status": "ok",
  "source_file": "sample_pci_test.pdf",
  "file_type": "pdf",
  "size_bytes": 1973,
  "pages": 1,
  "characters": 430,
  "language_api_version": "2026-05-15-preview",
  "language_model_versions": ["2026-05-01"],
  "timings": {"precheck_s": 0.037, "document_intelligence_s": 3.7, "language_s": 0.4},
  "pii_detected": true,
  "category_counts": {"Address": 1, "CVV": 2, "CreditCardNumber": 2, "DateTime": 2, "Email": 1, "Person": 2, "PhoneNumber": 1},
  "rule_only_detections": 0,
  "entity_count": 11,
  "entities": [
    {"category": "CreditCardNumber", "source": "language", "confidence_score": 1.0, "offset": 225, "length": 19, "masked_value": "*******************"}
  ],
  "masked_text": "PAYMENT CARD AUTHORIZATION FORM (TEST DATA ONLY)\nCustomer Name: *********** ... Card Number: ******************* Expiration Date: ***** CVV: *** ..."
}
```

| Field | Meaning |
|-------|---------|
| `source` | `language` (found by Azure AI Language) or `rule` (found only by the rule layer) |
| `rule_only_detections` | Values only the rule layer caught. A non-zero count means the Language service missed something, so track it over time |
| `language_api_version`, `language_model_versions` | Recorded for audit |
| `file_type`, `size_bytes` | From the pre-check. The type is detected from the file's first bytes |
| `timings` | Seconds spent in the pre-check, Document Intelligence, and Language |

## Service limits

All limits are for the Standard tiers (Document Intelligence S0; Language S0 and S). They were checked against Microsoft's documentation in November 2026. Limits change, so re-check the linked pages before you design around them.

### Document Intelligence, Read model (S0)

Source: [Document Intelligence service quotas and limits](https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/service-limits)

| Limit | Value | Adjustable |
|-------|-------|------------|
| Max document size | 500 MB | No |
| Max pages per analysis | 2,000 | No |
| Analyze requests (POST) per second | 15 | Yes, by support request |
| Get-result requests (GET) per second | 50 | Yes, by support request |
| Max OCR JSON response | 500 MB | No |
| Recommended polling interval | At most once every 2 seconds per request | n/a |

- Billing is per page. For PDF and TIFF, each page counts as one page.
- The `pages` parameter (for example `"1-100"`) analyzes a page range instead of the whole file.
- Supported file types for Read: PDF, JPEG, PNG, BMP, TIFF, HEIF, DOCX, PPTX, XLS.

### Azure AI Language, PII detection

Source: [Language service data limits](https://learn.microsoft.com/en-us/azure/ai-services/language-service/concepts/data-limits)

| Limit | Value |
|-------|-------|
| Characters per document, synchronous API | 5,120 (measured in text elements) |
| Documents per request, synchronous API | 5 |
| Documents per request, asynchronous API | 25, with a total of 125,000 characters across all documents |
| Max request size | 1 MB |
| Rate limit, S0 tier | 100 requests per second, 300 per minute |
| Rate limit, S tier | 1,000 requests per second, 1,000 per minute |
| Billing unit | 1 text record = 1,000 characters (billing only, not a cap) |

What happens when a limit is exceeded:

- **Synchronous:** an oversized document gets an invalid-document error, and the other documents in the request are still processed.
- **Asynchronous:** the whole request is rejected with `400 Bad Request`.

The pipeline uses 5,000-character chunks and 5 chunks per request (at most about 25,000 characters, well under 1 MB), which stays inside the synchronous limits.

### API versions

Source: [PII entity categories](https://learn.microsoft.com/en-us/azure/ai-services/language-service/personally-identifiable-information/concepts/entity-categories)

| API | Version | Notes |
|-----|---------|-------|
| Language, used by this pipeline | `2026-05-15-preview` | Required for `CVV`, `ExpirationDate`, `BankAccountNumber`, and `DateOfBirth`. Subject to Microsoft's preview terms |
| Language, current GA | `2026-05-01` | Does not detect CVVs (tested, see below) |
| Document Intelligence SDK | `azure-ai-documentintelligence` 1.0.2 | |

## Test results

All tests ran on November 22, 2026, against the `idpgtadoc` (East US) and `gta6langservice` resources, from a single laptop. Each figure comes from a single run, so expect variation between runs and regions.

### Test document

`scripts/generate_banking_pdf.py` produces a synthetic 500-page bank statement:

| Property | Value |
|----------|-------|
| Pages | 500 |
| File size | 861 KB (text PDF, not a scan) |
| Content per page | Account header and an 18-row transaction table |
| Cardholder blocks | 25, one every 20th page: name, email, phone, SSN, card type, card number, expiry, CVV |
| Card numbers | Public test numbers (Visa, Mastercard, American Express, Discover) |
| Extracted text | 528,527 characters (about 1,057 per page) |

### Detection accuracy

Scored with `scripts/score_results.py`. For each label, the scorer reads the value after the label in the masked output and counts a leak if it matches a planted value exactly.

| Planted value | Leaked | Detected by |
|---------------|--------|-------------|
| Card number | 0 / 25 | Language (`CreditCardNumber`) |
| CVV | 0 / 25 | Language (`CVV`) |
| Expiry date | 0 / 25 | Language (`DateTime`) |
| Email | 0 / 25 | Language (`Email`) |
| Phone | 0 / 25 | Language (`PhoneNumber`) |
| Cardholder name | 0 / 25 | Language (`Person`) |
| SSN | 25 / 25 | Not detected. Test-data artifact, see below |

- **SSN result.** The generator uses SSNs with a `000` area number, which is never issued, so the detector correctly ignores them. `scripts/probe_pii_categories.py` confirmed that a valid-format test SSN (`123-45-6789`) is detected and masked. To test SSN detection on your own data, use valid-format synthetic values.
- **Rule layer.** The Language service caught every card number, CVV, and expiry date on its own, so the rule layer added nothing on this document (`rule_only_detections: 0`). It is there as a backstop for layouts the service handles less well.

All entities returned for the 500-page document:

| Category | Count | Notes |
|----------|-------|-------|
| `BankAccountNumber` | 500 | The account number in each page header |
| `PhoneNumber` | 41 | 25 planted; 16 additional numbers also masked |
| `Person` | 28 | 25 planted names |
| `CreditCardNumber` | 25 | |
| `CVV` | 25 | |
| `DateTime` | 25 | Expiry dates |
| `Email` | 25 | |
| **Total** | **669** | |

### Processing time

Measured with `scripts/benchmark.py`:

| Stage | 1-page form (2 KB) | 500-page statement (861 KB) |
|-------|--------------------|-----------------------------|
| Characters extracted | 430 | 528,527 |
| Chunks / Language requests | 1 / 1 | 109 / 22 |
| Size and page pre-check | 37 ms | 26 ms |
| Document Intelligence | 2.5 s | 28.8 s (58 ms per page) |
| Language PII, 5 parallel requests | 0.3 s | 11.9 s |
| Rules, masking, validation | under 0.01 s | 0.1 s |
| **End to end** | **2.8 s** | **40.8 s** |

| Observation | Detail |
|-------------|--------|
| Document Intelligence is stable | 28.3 s to 28.8 s across three runs of the 500-page file |
| Parallel Language calls matter | The same 22 requests took 47.4 s one at a time and 11.9 s with 5 in parallel, about 4x faster |
| Rules and validation are cheap | About 0.1 s for 500 pages |
| The page pre-check is cheap | 26 ms for the 500-page PDF and 64 ms for a 2,000-page PDF. The 1-page figure is higher because it includes loading the PDF library |
| Command-line run agrees | `python languageservice.py` on the 500-page file took 40.2 s |

These numbers are for a text PDF. Scanned PDFs need full OCR and are usually much larger files, so expect them to be slower. They were not measured here. Test with your own scanned samples before you size anything.

### API version comparison

`scripts/probe_pii_categories.py` sent `Card number: 4111 1111 1111 1111. Expiration: 04/28. CVV: 123.` to the Language REST API:

| API version | Card number | Expiry `04/28` | CVV `123` |
|-------------|-------------|----------------|-----------|
| `2026-05-01` GA, default categories | Masked | Masked (as `DateTime`) | **Not masked** |
| `2026-05-15-preview`, explicit categories including `CVV` | Masked | Masked (as `DateTime`) | Masked (as `CVV`) |

This is why the pipeline uses the preview API with an explicit category list.

## Known gaps

| Gap | Risk | Suggested fix |
|-----|------|---------------|
| CVV and expiry detection rely on preview features | Preview terms apply, and behavior can change between versions | Keep the rule layer and output check, get compliance sign-off for preview use, and re-run `score_results.py` when the API or model version changes |
| No rule for SSNs or bank account numbers | These depend entirely on the Language service | Add label-anchored rules if your documents use consistent labels |
| Page pre-check covers PDF, TIFF, and single images only | PPTX, XLS, DOCX, and encrypted or damaged PDFs reach Document Intelligence without a page check, and fail there if they're too large | Count slides for PPTX and worksheets for XLS. Estimate DOCX pages from characters |
| Large files are processed in one Document Intelligence call | A failure means redoing the whole file | Split files over a few hundred pages into page ranges with the `pages` parameter |
| Concurrency is limited per process only | Several workers together can exceed Language's 300 requests-per-minute limit on S0 | Use a shared rate limiter in production. Retries on 429 are already in place |
| Overlapping chunks can report an entity twice if the two chunks detect slightly different spans | Duplicate entries in `entities` | Masking is unaffected. Merge overlapping spans if the list needs to be exact |
| Synchronous command-line tool | Not suitable for large uploads behind a web request | Use the target-state architecture above |
| Keys stored in `.env` | Key leakage | Use Microsoft Entra ID (managed identity) or Key Vault in production |
| Tested only on English text PDFs | Accuracy on scans, handwriting, and other languages is unknown | Build a labeled test set from your own document layouts |

## Enterprise approach for financial institutions

This section is guidance for banks, card issuers, and payment processors that want to run this kind of pipeline in production. It is not a compliance opinion. Confirm the details with your PCI QSA and your security team.

### 1. Treat the pipeline as part of your cardholder data environment

Any system that receives full card numbers is in PCI DSS scope. That includes the upload storage, the worker, both Azure resources, and their logs. Plan for network isolation, access control, and audit from the start, not as a later hardening step. PCI DSS also prohibits storing sensitive authentication data, including CVVs, after authorization. That makes CVV masking a requirement, not a nice-to-have.

### 2. Process asynchronously

The [target-state architecture](#target-state-architecture) separates intake from processing:

- **Intake returns in seconds.** The upload is validated, stored, scanned, and queued, and the caller gets `202 Accepted` with a job ID.
- **Processing runs in a worker.** A 500-page text PDF takes about 41 seconds, and scanned files take longer. That's too long to hold a web request open.
- **Delivery is by job ID.** The caller polls `GET /jobs/{id}`, honoring `Retry-After`, or receives a webhook.
- **Nothing sensitive is kept.** The original file and extracted text are deleted as soon as the masked result is written, and a storage retention policy removes anything left behind.

### 3. PCI/PII guardrails (defense in depth)

Do not rely on a single detector for card data. Layer the controls in this table:

| Guardrail | In this repo | Why it matters |
|-----------|--------------|----------------|
| Request categories explicitly, including `CVV` and `ExpirationDate` | Yes | Default categories miss CVVs and add heavy over-masking |
| Deterministic rules: Luhn card numbers, labeled CVV and expiry | Yes | Doesn't depend on a model or on preview features |
| Validate the output before returning it | Yes | Blocks any response where a card number or CVV survived |
| Fail closed on any error | Yes | Never returns partly masked text |
| Overlapping chunks | Yes | A value cut at a chunk boundary is still seen whole |
| Mask regardless of confidence | Yes | Every detected span is masked. Use `confidence_score` to route documents to human review, not to decide whether to mask |
| Never log content | Yes, in code | Log job IDs, page counts, category counts, timings, and versions only. Check that Azure diagnostic settings on both resources follow the same rule |
| Entra ID or Key Vault instead of keys | No | Keys in files and environment variables leak |
| Private endpoints, public network access disabled | No (Azure configuration) | Keeps card data off the public internet |
| Labeled regression test set | Synthetic only | Build one from your real layouts with synthetic values. Track recall per category and re-run on every API or model version change |
| Alert on `rule_only_detections` > 0 | No | Shows when the Language service starts missing values the rules catch |

### 4. Throughput and rate limits

| Service | Limit | Planning guidance |
|---------|-------|-------------------|
| Document Intelligence (S0) | 15 analyze requests per second, 50 get-result requests per second, both adjustable | Retry `429` with exponential backoff and honor `Retry-After`. Poll each request at most once every 2 seconds |
| Language (S0) | 100 requests per second, 300 per minute | At 5 chunks of 5,000 characters per request, 300 requests per minute is 7.5 million characters per minute. At the 1,057 characters per page measured here, that's about 7,000 pages per minute across all workers |
| Language (S) | 1,000 requests per second, 1,000 per minute | Check your resource's pricing tier before sizing |

- **Parallelism:** 5 parallel Language requests made that stage about 4x faster (47.4 s to 11.9 s). Use a bounded worker pool and a rate limiter shared across workers, so they don't exceed the per-minute limit together.
- **Text density varies.** Measure characters per page on your own documents before using the pages-per-minute estimate.

## File size and page recommendations

| Document | Recommendation |
|----------|----------------|
| Over 500 MB, or over 2,000 pages | Hard limits that can't be raised. Reject at upload, or split the PDF into parts before submitting |
| 500 to 2,000 pages | Process as one Document Intelligence call, or split into page ranges with the `pages` parameter so ranges run in parallel and a failure only retries one range. Page-range splitting was not measured here, so benchmark it on your documents |
| Up to 500 pages, text PDF | One Document Intelligence call is fine. Measured: 28.8 s for Document Intelligence and 40.8 s end to end for 500 pages |
| Scanned PDFs and images | Expect larger files and longer OCR times than the text PDF measured here. Benchmark with real scans before sizing the deployment |

General rules:

- **Validate before upload.** Check file type, file size, and page count. A rejected upload costs nothing, while a failed analysis wastes time and quota. Size comes from file metadata. Pages have to be counted inside the file, which took 26 ms for 500 PDF pages. See [How the size and page checks work](docs/architecture.md#how-the-size-and-page-checks-work).
- **Choose chunk boundaries carefully.** Split Language input at line or paragraph boundaries and overlap chunks, as this pipeline does. Keep the rule layer as a second line of defense.
- **Use the async Language API for bulk jobs if you need fewer requests.** It accepts 25 documents per request, but caps the total at 125,000 characters, which is 25 chunks of 5,000 characters. It rejects the whole request if any document is too large, so validate chunk sizes first.
- **Request only the categories you need.** Each extra general category adds entities to review without protecting more card data.
