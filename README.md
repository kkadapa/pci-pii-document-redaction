# PCI/PII Document Redaction with Azure Document Intelligence and Azure AI Language

This project takes an uploaded document that contains payment card (PCI) or personal (PII) data and returns JSON with the sensitive values masked. Two Azure services do the work:

1. **Azure AI Document Intelligence** reads the document (including scanned pages) and extracts the text.
2. **Azure AI Language** (PII detection) finds sensitive values in that text.

A rule layer then catches card numbers, CVVs, and expiry dates the Language service misses. A final check blocks the response if any card number or CVV survives masking.

The response contains only masked text and entity metadata (category, position, length, confidence). The original sensitive values are never returned or logged.

> **Status: prototype.** On the 500-page synthetic test, every planted card number, CVV, expiry date, email, phone number, and name was masked. CVV and expiry detection rely on Language API *preview* features. Read [Known gaps](#known-gaps) and [Enterprise approach](#enterprise-approach-for-financial-institutions) before using this with real card data.

## Contents

- [How it works](#how-it-works)
- [Project files](#project-files)
- [Setup and usage](#setup-and-usage)
- [Service limits](#service-limits)
- [Test results](#test-results)
- [Known gaps](#known-gaps)
- [Enterprise approach for financial institutions](#enterprise-approach-for-financial-institutions)
- [File size and page recommendations](#file-size-and-page-recommendations)

## How it works

```
PDF / image upload
        |  reject if over 500 MB
        v
1. Azure AI Document Intelligence (prebuilt-read)        resource: idpgtadoc
        |  extracted text
        v
2. Split into chunks of up to 5,000 characters, ending at line breaks,
   with 100 characters of overlap between chunks
        |
        v
3. Azure AI Language PII detection, REST API 2026-05-15-preview   resource: gta6langservice
   - explicit category list, including CVV and ExpirationDate
   - 5 chunks per request, 5 requests in parallel
   - retries on HTTP 429 and 5xx, honoring Retry-After
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

The pipeline **fails closed**. If any Language request fails, any chunk returns an error, or the final check finds a surviving card number or CVV, it returns `{"status": "error"}` and no text at all. The error message never includes document content.

### Categories requested

| Group | Categories |
|-------|------------|
| Payment card | `CreditCardNumber`, `CVV` (preview), `ExpirationDate` (preview) |
| Bank and tax | `USBankAccountNumber`, `BankAccountNumber` (preview), `ABARoutingNumber`, `SWIFTCode`, `InternationalBankingAccountNumber`, `USSocialSecurityNumber`, `USIndividualTaxpayerIdentification` |
| Personal | `Person`, `Email`, `PhoneNumber`, `Address`, `DateOfBirth` (preview) |

To change the list, edit `PII_CATEGORIES` in `languageservice.py`. General categories like `Organization` and `DateTime` are left out on purpose. In testing they made up 93% of detections and masked merchant names and transaction dates. The service sometimes still labels an expiry date as `DateTime`. That entity is masked anyway.

## Project files

| File | Purpose |
|------|---------|
| `languageservice.py` | The pipeline. Run it on a file, or import `process_document(path)` |
| `scripts/generate_banking_pdf.py` | Generates a synthetic 500-page bank statement PDF and a ground-truth file listing every planted value |
| `scripts/score_results.py` | Scores pipeline output against the ground truth |
| `scripts/benchmark.py` | Times each stage, and compares 1 worker with N parallel workers for Language calls |
| `scripts/probe_pii_categories.py` | Calls the Language REST API to compare what each API version detects |
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
  "pages": 1,
  "characters": 430,
  "language_api_version": "2026-05-15-preview",
  "language_model_versions": ["2026-05-01"],
  "timings": {"document_intelligence_s": 2.5, "language_s": 0.3},
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

- `source` is `language` or `rule`.
- `rule_only_detections` counts values that only the rule layer caught. A non-zero count means the Language service missed something, which is worth tracking over time.
- `language_api_version` and `language_model_versions` are included for audit.

## Service limits

Checked against Microsoft's documentation in November 2026. Limits change, so re-check the linked pages before you design around them.

### Document Intelligence, Read model

Source: [Document Intelligence service quotas and limits](https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/service-limits)

| Limit | Free (F0) | Standard (S0) | Adjustable |
|-------|-----------|---------------|------------|
| Max document size | 4 MB | 500 MB | No |
| Max pages per analysis | 2 | 2,000 | No |
| Analyze requests (POST) per second | 1 | 15 | S0: yes, by support request |
| Get-result requests (GET) per second | 1 | 50 | S0: yes, by support request |
| Max OCR JSON response | 500 MB | 500 MB | No |

- F0 analyzes only the first two pages of a request, so it is for testing only.
- Billing is per page. For PDF and TIFF, each page counts as one page.
- The `pages` parameter (for example `"1-100"`) analyzes a page range instead of the whole file.

### Azure AI Language, PII detection

Source: [Language service data limits](https://learn.microsoft.com/en-us/azure/ai-services/language-service/concepts/data-limits)

| Limit | Value |
|-------|-------|
| Characters per document, synchronous API | 5,120 (measured in text elements) |
| Documents per request, synchronous API | 5 |
| Documents per request, asynchronous API | 25, with a total of 125,000 characters across all documents |
| Max request size | 1 MB |
| Rate limit, S0 / F0 tier | 100 requests per second, 300 per minute |
| Rate limit, S / multi-service tier | 1,000 requests per second, 1,000 per minute |
| Billing unit | 1 text record = 1,000 characters (billing only, not a cap) |

What happens when a limit is exceeded:

- **Synchronous:** an oversized document gets an invalid-document error, and the other documents in the request are still processed.
- **Asynchronous:** the whole request is rejected with `400 Bad Request`.

The pipeline uses 5,000-character chunks and 5 chunks per request, which stays under the synchronous limits.

### API and SDK versions

| | Version | Used here | Notes |
|---|---|---|---|
| Language API, preview | `2026-05-15-preview` | Yes, via REST | Needed for `CVV`, `ExpirationDate`, `BankAccountNumber`, and `DateOfBirth`. Subject to Microsoft's preview terms |
| Language API, GA | `2026-05-01` | No | Does not detect CVVs (tested) |
| `azure-ai-textanalytics` SDK | 5.4.0 (latest on PyPI) | No longer used | Calls API version `2023-04-01` at most, which has no CVV or expiry categories |
| `azure-ai-documentintelligence` SDK | 1.0.2 | Yes | |

Source: [PII entity categories](https://learn.microsoft.com/en-us/azure/ai-services/language-service/personally-identifiable-information/concepts/entity-categories)

## Test results

All tests ran on November 22, 2026, against the `idpgtadoc` (East US) and `gta6langservice` resources, from a single laptop. Each figure comes from one run, so expect variation between runs and regions.

Two versions of the pipeline were tested:

- **v1:** the first version. It used the `azure-ai-textanalytics` SDK (API `2023-04-01`) with default categories, sequential requests, and no rule layer.
- **v2:** the current version, described above.

### Test document

`scripts/generate_banking_pdf.py` produces a synthetic 500-page bank statement:

- Every page has an account header and an 18-row transaction table.
- Every 20th page (25 pages in total) also has a cardholder block: name, email, phone, SSN, card type, card number, expiry, and CVV.
- Card numbers are public test numbers. Names and accounts are fake.
- The PDF is 861 KB. It is a text PDF, not a scan.

### Detection accuracy

Scored with `scripts/score_results.py`. For each label, it reads the value after the label in the masked output and counts a leak if it matches a planted value exactly.

| Planted value | v1 leaked | v2 leaked |
|---------------|-----------|-----------|
| Card number | 0 / 25 | 0 / 25 |
| CVV | **25 / 25** | 0 / 25 |
| Expiry date | **24 / 25** | 0 / 25 |
| Email | 0 / 25 | 0 / 25 |
| Phone | 0 / 25 | 0 / 25 |
| Cardholder name | 0 / 25 | 0 / 25 |
| SSN | 25 / 25 | 25 / 25 (test-data artifact, see below) |

**About the SSN result.** The generator uses SSNs with a `000` area number, which is never issued, so the detector correctly ignores them. `scripts/probe_pii_categories.py` confirmed that a valid-format test SSN (`123-45-6789`) is detected and masked. To test SSN detection on your own data, use valid-format synthetic values.

**About the v2 CVV and expiry results.** In v2, the Language service itself caught all 25 CVVs and all 25 expiry dates. The rule layer found nothing extra (`rule_only_detections: 0`). It is there as a backstop for layouts the service handles less well.

**About a scoring mistake.** An earlier version of the scorer searched for each value anywhere in the masked text. That reported 18 false CVV leaks in v2, because 3-digit CVV values also appear inside amounts and balances on other lines. The label-based scorer fixes this.

**Over-masking dropped sharply:**

| | v1 | v2 |
|---|---|---|
| Total entities | 16,981 | 669 |
| `Organization` (merchant names) | 6,814 | not requested |
| `DateTime` (transaction dates) | 9,001 | 25 (expiry dates labeled as dates) |
| `BankAccountNumber` | not detected | 500 (one account number per page header) |
| `PhoneNumber` | 529 | 41 (25 planted, so 16 extra) |

### Processing time

Measured with `scripts/benchmark.py`:

| Stage | 1-page sample (2 KB) | 500-page statement (861 KB) |
|-------|----------------------|-----------------------------|
| Characters extracted | 430 | 528,527 (about 1,057 per page) |
| Language requests | 1 | 22 (109 chunks) |
| Document Intelligence | 2.5 s | 28.8 s (58 ms per page) |
| Language, 1 worker | 0.3 s | 47.4 s |
| Language, 5 parallel workers (default) | 0.3 s | 11.9 s |
| Rules, masking, validation | under 0.01 s | 0.1 s |
| **End to end, v2 (5 workers)** | **2.8 s** | **40.8 s** |
| End to end, v1 (for comparison) | 4.1 s | 60.7 s |

What the numbers show:

- **Document Intelligence** took under 30 seconds for 500 pages in a single call, and was stable across runs (28.3 to 28.8 s).
- **The preview Language API was slower per request.** On one worker it took 47.4 s, against 32.0 s for v1's SDK path. Running 5 requests in parallel more than made up for it.
- **The rule layer and validation** add about 0.1 s for 500 pages.
- **A separate CLI run** of v2 on the 500-page file took 40.2 s, consistent with the benchmark.

These numbers are for a text PDF. Scanned PDFs need full OCR and are usually much larger files, so expect them to be slower. They were not measured here. Test with your own scanned samples before you size anything.

### API version comparison

`scripts/probe_pii_categories.py` sent `Card number: 4111 1111 1111 1111. Expiration: 04/28. CVV: 123.` to the Language REST API:

| API version | Card number | Expiry `04/28` | CVV `123` |
|-------------|-------------|----------------|-----------|
| `2026-05-01` GA, default categories | Masked | Masked (as `DateTime`) | **Not masked** |
| `2026-05-15-preview`, explicit categories including `CVV` | Masked | Masked (as `DateTime`) | Masked (as `CVV`) |

## Known gaps

| Gap | Risk | Suggested fix |
|-----|------|---------------|
| CVV and expiry detection rely on preview features | Preview terms apply, and behavior can change between versions | Keep the rule layer and output check, get compliance sign-off for preview use, and re-run `score_results.py` when the API or model version changes |
| No rule for SSNs or bank account numbers | These depend entirely on the Language service | Add label-anchored rules if your documents use consistent labels |
| Page count is not checked before upload | Files over 2,000 pages fail at Document Intelligence instead of up front | Count pages client-side before submitting |
| Large files are processed in one Document Intelligence call | A failure means redoing the whole file | Split files over a few hundred pages into page ranges with the `pages` parameter |
| Concurrency is limited per process only | Several workers together can exceed Language's 300 requests-per-minute limit on S0 | Use a shared rate limiter in production. Retries on 429 are already in place |
| Overlapping chunks can report an entity twice if the two chunks detect slightly different spans | Duplicate entries in `entities` | Masking is unaffected. Merge overlapping spans if the list needs to be exact |
| Synchronous command-line tool | Not suitable for large uploads behind a web request | Use the queued architecture below |
| Keys stored in `.env` | Key leakage | Use Microsoft Entra ID (managed identity) or Key Vault in production |
| Tested only on English text PDFs | Accuracy on scans, handwriting, and other languages is unknown | Build a labeled test set from your own document layouts |

## Enterprise approach for financial institutions

This section is guidance for banks, card issuers, and payment processors that want to run this kind of pipeline in production. It is not a compliance opinion. Confirm the details with your PCI QSA and your security team.

### 1. Treat the pipeline as part of your cardholder data environment

Any system that receives full card numbers is in PCI DSS scope. That includes the upload storage, the worker, both Azure resources, and their logs. Plan for network isolation, access control, and audit from the start, not as a later hardening step. PCI DSS also prohibits storing sensitive authentication data, including CVVs, after authorization. That makes CVV masking a requirement, not a nice-to-have.

### 2. Reference architecture

```
Client
  |  upload (TLS)
  v
Upload API --> validate (type, size <= 500 MB, pages <= 2,000, malware scan)
  |  returns job ID
  v
Blob Storage (private endpoint, encryption, short retention)
  |
  v
Queue (Service Bus) --> Worker (Functions or Container Apps)
                          |
                          |-- Document Intelligence: whole file, or page ranges for large files
                          |-- Chunk text (<= 5,000 chars, with overlap)
                          |-- Language PII: parallel batches, shared rate limiter, 429 retry
                          |-- Rule layer: Luhn card numbers, labeled CVV and expiry
                          |-- Output check: fail if any card number or CVV survives
                          v
                     Masked JSON result store --> client polls by job ID
```

- **Make processing asynchronous.** A 500-page text PDF took about 40 seconds in testing, and scanned files take longer. That's too long for a synchronous web request. Return a job ID and let the client poll or receive a callback.
- **Delete originals and extracted text** as soon as the masked result is written. Set a retention policy on storage so nothing is kept by accident.

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

- **Document Intelligence** allows 15 analyze requests per second by default on S0. Ask Microsoft support for more if you need it. Retry `429` responses with exponential backoff, and honor the `Retry-After` header. Microsoft also recommends polling for results no more than once every 2 seconds per request.
- **Language** on S0 allows 300 requests per minute. At 5 chunks of 5,000 characters per request, that's 7.5 million characters per minute. At the roughly 1,057 characters per page measured on the synthetic statement, that's about 7,000 pages per minute across all workers. Real documents have different text density, so measure your own. Check your Language resource's pricing tier, because the S tier allows 1,000 requests per minute.
- **Parallelism:** 5 parallel Language requests made that stage about 4x faster in testing (47.4 s to 11.9 s). Use a bounded worker pool and a rate limiter shared across workers, so they don't exceed the per-minute limit together.

## File size and page recommendations

| Document | Recommendation |
|----------|----------------|
| Over 500 MB, or over 2,000 pages | Hard service limits on every tier. Reject at upload, or split the PDF into parts before submitting |
| 500 to 2,000 pages | Process as one Document Intelligence call, or split into page ranges with the `pages` parameter so ranges run in parallel and a failure only retries one range. Page-range splitting was not measured here. Benchmark it on your documents |
| Up to 500 pages, text PDF | One Document Intelligence call is fine. Measured: about 29 s for 500 pages, about 41 s end to end |
| Scanned PDFs and images | Expect larger files and longer OCR times than the text PDF measured here. Benchmark with real scans before sizing the deployment |
| Testing on the free tier (F0) | Limited to 4 MB and 2 pages per request. Use S0 for any realistic test |

General rules:

- **Validate before upload.** Check MIME type, file size, and page count. A rejected upload costs nothing, while a failed analysis wastes time and quota.
- **Choose chunk boundaries carefully.** Split Language input at line or paragraph boundaries and overlap chunks, as this pipeline does. Keep the rule layer as a second line of defense.
- **Use the async Language API for bulk jobs if you need fewer requests.** It accepts 25 documents per request, but caps the total at 125,000 characters, which is 25 chunks of 5,000 characters. It rejects the whole request if any document is too large, so validate chunk sizes first.
- **Request only the categories you need.** Dropping `Organization` and `DateTime` cut the 500-page output from 16,981 entities to 669, without losing any planted sensitive value.
