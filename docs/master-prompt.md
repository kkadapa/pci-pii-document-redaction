# Master prompt: rebuild the PCI/PII redaction project in a new environment

Paste everything below the line into a coding agent (Claude Code or similar) that has a shell, a Python 3.11+ environment, Google Chrome, optionally LibreOffice, and an empty working directory. Before you start, put the four Azure values in a local `.env` file yourself. Never paste keys into the prompt or the chat.

Everything in the prompt was learned by building this project once. The measured numbers it mentions are **what the first build observed in November 2026. The agent must re-measure and must not copy them.**

---

## ROLE AND GOAL

You are building, testing, documenting, and publishing a prototype that removes payment card (PCI) and personal (PII) data from uploaded documents and returns JSON with the sensitive values masked.

Pipeline: **upload document → Azure AI Document Intelligence (OCR/text extraction) → Azure AI Language PII detection → rule layer → mask → validate → JSON response.**

Deliverables:

1. A working pipeline (`languageservice.py`) with a CLI.
2. Realistic synthetic test data at 500 and 2,000 pages, with ground truth.
3. Live tests of every service limit, with evidence screenshots.
4. Two architecture diagrams (logical and technical with official Azure icons) plus walkthrough docs.
5. A README with verified limits, results, known gaps, and enterprise guidance.
6. A 30-ish slide team deck (PPTX and PDF).
7. Everything published to a **private** GitHub repo.

## OPERATING RULES (read first, they override your defaults)

- **Evidence over assertion.** Every number in the docs must come from a run you did or from Microsoft's documentation you fetched. Cite the doc URL for documented limits. If you could not verify something, say "not tested" in the docs. Do not guess.
- **Report only current results.** No "v1 vs v2" history, no "earlier we tried" narrative in the README. History lives in git.
- **No free tier (F0) content** anywhere in the docs. Standard tiers only (Document Intelligence S0; Language S0/S).
- **Secrets.** Read endpoints and keys only from `.env`. Never print, log, commit, or screenshot them. `.env` is in `.gitignore`. If a command would reveal a key, do not run it.
- **Commit and push only after the user asks.** Do not create the GitHub repo or push on your own initiative. Confirm before anything outward-facing.
- **Fail closed.** The pipeline must never return partly masked text.
- **No document content in logs or error messages.**
- **Plain, specific writing** in docs: no marketing language, no filler. Tables for numbers.
- When a test result contradicts the documentation or your expectation, **report the contradiction and fix the design**, do not hide it.

## INPUTS YOU NEED FROM THE USER (ask once, at the start)

Two separate Azure AI resources, each with its own endpoint and key (a key from one does not work on the other and returns `401`):

```
AZURE_DOCINTEL_ENDPOINT=https://<custom-subdomain>.cognitiveservices.azure.com/
AZURE_DOCINTEL_KEY=...
AZURE_LANGUAGE_ENDPOINT=https://<custom-subdomain>.cognitiveservices.azure.com/
AZURE_LANGUAGE_KEY=...
```

Also ask for: the GitHub repo name and visibility (default private), and whether Docker/LibreOffice/Chrome are available. Verify the tiers from the services' own `429` messages during testing, do not assume them.

## ARCHITECTURE DECISIONS ALREADY MADE (do not reopen)

- **Keep API Management** in the target design.
- **Blob Storage** is the only data store (one JSON blob per job, ETag concurrency, index tags, lifecycle deletion). **No Cosmos DB.**
- The **redaction worker runs on Azure Functions** (Service Bus trigger). **No Container Apps, no AKS.** Mention Container Apps only as the fallback if scanned documents exceed Functions timeouts.
- The file **never passes through API Management**. The client gets a short-lived write-only SAS upload URL (valet key pattern) and uploads straight to a quarantine container.
- Checks are split: API Management checks the *declared* size and type early; the Intake Function (after Defender for Storage scans) does the *authoritative* size, type, and page-count checks on the real file.
- Every job is bound to the creator's Entra `oid`; other callers get `404`.
- No keys in the target design: managed identities, `disableLocalAuth=true`, private endpoints.
- Language is called through **REST**, not the SDK (see below).
- Mask-or-block is a business decision; implement both (`--pci-mode mask|block`; block maps to HTTP `422`).
- Only the pre-check and the worker logic are implemented in code. The rest of the Azure design is documentation and is labeled "target design, not deployed".

## STACK AND VERSIONS

Python packages (pin exactly, then re-verify they install; if a pin no longer exists, pick the nearest and note it):

```
azure-ai-documentintelligence==1.0.2     # API 2024-11-30
azure-core==1.41.0
python-dotenv==1.2.4
requests==2.34.2
pypdf==7.1.1
pillow==13.0.0
reportlab==5.1.0
python-pptx==1.0.2
```

- Document Intelligence model: `prebuilt-read`.
- Language PII: REST `POST {endpoint}/language/:analyze-text`, API version **`2026-05-15-preview`**, with an explicit `piiCategories` list, `stringIndexType: UnicodeCodePoint`.
- **Why REST:** `azure-ai-textanalytics` 5.4.0 supports only API `2023-04-01`, which has no `CVV` or `ExpirationDate` category. The GA API `2026-05-01` also misses CVVs with default categories. **Verify both claims yourself** with a probe script (see phase 2) before writing them in the README.

## PHASE 0: Project setup

- Create the repo layout: `languageservice.py`, `scripts/`, `docs/`, `docs/evidence/`, `docs/icons/azure/`, `docs/presentation/`, `test_data/`, `requirements.txt`, `.gitignore` (`.env`, `.venv/`, `__pycache__/`, `*.pyc`, `.vscode/`, `.DS_Store`), `README.md`.
- Create a virtual environment **in a path without spaces** (a space in the path breaks venv launchers) and install the pinned requirements.
- Load `.env` with python-dotenv. Fail with a clear message naming the missing variable.

## PHASE 1: The pipeline (`languageservice.py`)

Constants: `MAX_FILE_BYTES = 500*1024*1024`, `MAX_PAGES = 2000`, `MAX_CHARS_PER_DOC = 5000` (Language limit is 5,120), `CHUNK_OVERLAP = 100`, `MAX_DOCS_PER_REQUEST = 5`, `PARALLEL_REQUESTS = 5`, `MAX_RETRIES = 8`, `DOCINTEL_RETRIES = 10`, `PCI_BLOCK_CATEGORIES = {"CreditCardNumber", "CVV"}`.

`PII_CATEGORIES` (explicit, in this order of groups): CreditCardNumber, CVV, ExpirationDate, USBankAccountNumber, BankAccountNumber, ABARoutingNumber, SWIFTCode, InternationalBankingAccountNumber, USSocialSecurityNumber, USIndividualTaxpayerIdentification, Person, Email, PhoneNumber, Address, DateOfBirth. Leave out general categories (Organization, DateTime): on transaction-heavy documents they mask every merchant and date.

Steps:

0. **Pre-check** (`precheck(path)` → `{"file_type","size_bytes","pages_counted"}`), before any Azure call:
   - size from file metadata; reject over 500 MB;
   - real file type from magic bytes, not the extension;
   - page count inside the file: PDF via pypdf, TIFF via Pillow `n_frames`, single images = 1; reject over 2,000;
   - if pages can't be counted (encrypted/damaged PDF, Office files), let it through with `pages_counted=None`.
1. **Document Intelligence** `prebuilt-read` through the SDK. Configure the SDK retry policy (`retry_total/connect/read=10`, `retry_backoff_factor=1.0`, `retry_backoff_max=30`). Wrap `begin_analyze_document` and retry only `ServiceRequestError` a few times.
   - **Fail closed if the returned page count differs from the pre-check count.** The first build found that Document Intelligence silently analyzes only the first 2,000 pages of a longer file and reports `succeeded`. Re-test this yourself (phase 4) and keep the guard either way.
2. **Chunk** the text to ≤ 5,000 characters, ending at line breaks, with 100 characters of overlap.
3. **Language PII** via REST, 5 chunks per request, 5 requests in parallel (thread pool, one `requests.Session` per thread). Retry 429 and 5xx honoring `Retry-After`, and retry connection errors, with exponential backoff and jitter, up to 8 attempts. Any chunk error fails the whole job. Do not rely on a global session.
4. **Rule layer** over the full text: Luhn-valid 13–19 digit numbers (allow spaces/dashes); 3–4 digits after labels CVV/CVC/CVV2/CID/CSC/Security code; month/year after Exp/Expiry/Expiration/Valid thru.
5. **Mask** the union of all detected spans (Language + rules) with `*`, regardless of confidence.
6. **Validate**: if any Luhn-valid card number or labeled CVV remains in the masked text, raise an error.
7. **PCI policy**: `mask` returns masked text; `block` returns `{"status":"blocked","reason":"Payment card data detected","source_file","pages","pci_categories_found","timings"}` with no text and no positions.

Output JSON (mask mode): `status`, `source_file`, `file_type`, `size_bytes`, `pages`, `characters`, `language_api_version`, `language_model_versions`, `timings` (`precheck_s`, `document_intelligence_s`, `language_s`), `pii_detected`, `category_counts`, `rule_only_detections`, `entity_count`, `entities[]` (`category`, `source` = `language`|`rule`, `confidence_score`, `offset`, `length`, `masked_value`), `masked_text`. Never include original values.

CLI: `python languageservice.py <file> [--pci-mode mask|block]`. Exit 0 whenever the pipeline completes (masked or blocked), exit 1 on `PipelineError`, `HttpResponseError`, or `AzureError`, printing error JSON `{"status":"error","message":...}` with no document content.

## PHASE 2: Verify the category claim

Write `scripts/probe_pii_categories.py`. Send `Card number: 4111 1111 1111 1111. Expiration: 04/28. CVV: 123.` to (a) the GA API with default categories and (b) the preview API with explicit categories. Record which values each masks. Put the result table in the README. If the GA API now detects CVVs, update the "why preview" explanation accordingly. Do not keep a claim that your probe contradicts.

## PHASE 3: Realistic test data and scoring

Write `scripts/generate_banking_pdf.py` (reportlab canvas, `invariant=1`, fixed seed 42 so output is byte-identical each run; options `--pages`, `--out`). Output `banking_statements_<N>p.pdf` and `ground_truth_<N>p.json` (`total_pages`, `statements`, `page_types`, `planted`).

The document must look like a real statement batch, **not** a card number on every page:

- Each statement: an account summary page, 1–4 transaction pages (28 rows each), an interest-and-fees page, a disclosures page.
- Card numbers on ordinary pages are already masked ("Card ending in 4444", "XXXX XXXX XXXX 4444").
- Full card data only on occasional forms attached to about one statement in five (`FORM_PROBABILITY = 0.2`), at irregular positions: Card Dispute, Recurring Payment Authorization, Balance Transfer Request. Form labels: `Cardholder:`, `Email:`, `Phone:`, `SSN on file:`, `Card type:`, `Card number:`, `Expiration:`, `CVV:`.
- Fictional data only: public test card numbers (Visa, Mastercard, Amex, Discover), made-up names/addresses, and published example SSNs (`123-45-6789`, `078-05-1120`, `219-09-9999`). **Do not use SSNs starting with `000`, `666`, or `9xx`-invalid ranges**: the service doesn't recognize never-issued SSNs and you will chase false leaks.
- Generate 500 and 2,000 pages. Commit both PDFs and ground-truth files.

Write `scripts/score_results.py`: **label-anchored** scoring. For each form field, read the value after its label in the masked output and count a leak only if it exactly matches the planted value. Do **not** substring-search 3-digit CVVs across the text (false positives). Also score summary-page customer names and addresses against the generator's page plan. Default ground-truth path `test_data/ground_truth_500p.json`.

Write `scripts/benchmark.py`: time Document Intelligence, Language with 1 worker versus N workers, and the rule layer.

Write `scripts/test_precheck.py` (offline, no Azure calls): at least 10 cases: the committed 500 and 2,000 page documents, generated PDFs at 2,000 and 2,001 blank pages, TIFFs at 3 and 2,001 frames, a PNG, a damaged PDF, a text file. Expected: pass/reject as designed.

Run the pipeline in mask mode on both documents (save `test_data/results_*.json`) and block mode on the 500-page document. Score them. Run each timing at least 3 times where practical and report the range.

## PHASE 4: Live service-limit tests with evidence

Write `scripts/test_service_limits.py`, calling the services **directly** (bypassing your pre-check) so the services' own enforcement is what's tested. Each test writes a plain-text transcript to `docs/evidence/logs/<id>.txt` containing: limit under test, documentation source, what was sent, what came back, and a verdict. No keys, no document content.

Tests (ids): `di-pages` (2,001-page PDF), `di-rate` (60 analyze requests, 30 in parallel), `di-size` (501 MiB), `lang-chars` (6,000-char + 500-char documents, sync), `lang-docs-sync` (6 docs), `lang-docs-async` (26 docs), `lang-chars-async` (25 docs × 5,100 chars = 127,500), `lang-rate` (default 1,100 requests, 40 parallel; env `LANG_RATE_REQUESTS`), `pipeline-precheck` (your own pre-check on a 2,001-page PDF and a 501 MiB file).

Documented limits to test against (re-fetch from Microsoft Learn first and cite them):

- Document Intelligence S0: 500 MB, 2,000 pages, 15 analyze/s, 50 get/s, poll at most every 2 s.
- Language sync: 5,120 chars/doc, 5 docs/request, 1 MB/request. Async: 25 docs, 125,000 chars total. Rate: S0 100/s and 300/min; S 1,000/s and 1,000/min.

Implementation pitfalls the first build hit (avoid them):

- **501 MiB test:** build a `RandomBody` class with `__len__` and `read()` so `requests` sends a real `Content-Length`. A generator body sends chunked encoding and an empty `200`. Stream it; do not allocate 501 MiB in memory. Judge the result only after bytes were sent: a TLS handshake failure with 0 bytes sent is not "enforced", retry it.
- **Verdict honesty:** if a service returns a different status than documented (the first build saw `413` instead of the documented `400` for the async character total), mark it "enforced, different code than documented", not a failure.
- **Silent truncation:** record the result of `di-pages` exactly. If Document Intelligence accepts the file and returns 2,000 pages with `succeeded`, that is the single most important finding; document it prominently and keep the page-mismatch guard.
- **Rate-limit tests are billed** and may be throttled earlier than the documented number if you ran a burst moments before. Say so; do not claim an exact threshold you can't read from the test.
- **Network flakiness:** on the first build's network, 17–23% of new TLS connections failed the handshake. Measure it (don't assume), keep it separate from limit responses in the transcripts, and rely on the retry logic.
- Confirm the pricing tier of each resource from the `429` message text.

Write `scripts/render_evidence.py`: render each transcript as a terminal-style PNG with headless Chrome (`--headless=new`, window width 1500, height from line count; join lines with `""` when each line is already a `<div>` or you get double spacing). Colors only: green prompt lines, grey comments, red errors, amber for "SILENTLY" and "page says 400" verdicts, green for enforced. Output `docs/evidence/01-…10-*.png`, including a `pipeline-results` image (scoring plus block mode) and a `00-test-document-sample-pages.png` showing four pages of the 500-page batch. When rendering PDF pages to images, composite on a white background (transparent pages render black).

## PHASE 5: Architecture diagrams and docs

- `scripts/render_architecture.py` → `docs/architecture.svg` (logical flow, 13 steps from job creation to masked JSON, limits and measured timings, a time-budget panel for 500 and 2,000 pages).
- `scripts/render_technical_architecture.py` → `docs/technical-architecture.svg`: each Azure service with **official Azure architecture icons**. Download the icon set from Microsoft's Azure Architecture Center, put only the icons you use in `docs/icons/azure/`, include Microsoft's terms in a README there, and embed them as base64 data URIs so the SVG is self-contained. Services: Client, Application Gateway with WAF, API Management, Functions (Create job, Intake, Redaction worker, Job status), Blob Storage (job store, quarantine, results), Defender for Storage, Event Grid, Service Bus, Document Intelligence, Language, Entra ID, Managed identities, Key Vault, Private endpoints, VNet, Application Insights, Log Analytics. Mark components whose logic exists in `languageservice.py` as **IN REPO** and everything else as target design.
- `docs/architecture.md`: logical flow, sequence diagram (Mermaid), step-by-step, how the size and page checks work, time budget, failure table.
- `docs/technical-architecture.md`: key design decisions, request flow table, what API Management does (policy table: `validate-azure-ad-token`, `set-header` for `x-caller-oid`, `rate-limit-by-key`/`quota-by-key`, `choose`+`return-response` for declared size/type), job store layout, API contract (`POST /jobs`, `PUT {uploadUrl}`, `GET /jobs/{id}` with 202/200/422/404), identity and roles table (least privilege, scoped to containers), network notes (including that Document Intelligence reading a blob with public access off needs a configured path that was **not tested**), why Functions for the worker with the timeout/memory caveats, and what exists in the repo today.
- Optional but valued: a comparison with a gateway-only design (API Management does everything) if the user supplies the article; credit the author by name and link, and compare only what the article actually says.
- Fetch any Microsoft limit you mention (for example API Management payload limits per tier) and cite the source. If you cannot verify it, drop it.

## PHASE 6: README

Sections: Status (prototype, honest summary), Contents, Target-state architecture (both diagrams), How the pipeline works (steps 0–7, categories requested, why REST), Where the pre-check runs in production (API Management vs Intake Function table), Project files, Setup and usage (including `.env` example with placeholders, example output, block-mode output), Service limits (tables with source URLs and verification month), Test results (test documents, detection accuracy, all-entities table showing over-masking, processing time with per-page rows, size/page pre-check table, block mode, API version comparison), Service limit evidence (summary table of all 9 tests plus all screenshots and "what this means for the design"), Known gaps, Enterprise approach (PCI scope, async processing, defense-in-depth guardrails table, throughput and rate limits), File size and page recommendations.

Content rules:

- **Processing-time table must include per-page rows**, and a note that Language time scales with characters and request count, not pages. A 1-page sample's per-request overhead is not a per-page rate.
- Known gaps must list what you actually observed, including: names printed in capitals missed, heavy over-masking (transaction references flagged as phone numbers, merchant locations as addresses), reliance on preview features, page counting limited to PDF/TIFF/images, single-process concurrency, keys still in `.env`, synthetic English text PDFs only, flaky network path.
- Enterprise section must say plainly that any system receiving full card numbers is in PCI DSS scope, that CVVs may not be stored after authorization, and that this is guidance, not a compliance opinion.

## PHASE 7: Team deck

`scripts/build_presentation.py` → `docs/presentation/pci-pii-redaction-walkthrough.pptx` plus PDF via LibreOffice (skip PDF with a message if it's absent). About 30 slides, 16:9, speaker notes on every slide, five parts: (1) problem and result, (2) pipeline and how we got here (including what broke and what changed), (3) test results, (4) service limits tested live with the evidence screenshots and the silent-truncation slide, (5) target architecture, request flow, design decisions, mask or block, honest enterprise-readiness assessment, known gaps, recommendations, next steps, where to find everything.

Rules:

- Every number comes from the README or evidence logs.
- python-pptx cannot embed SVG: render the SVG diagrams to PNG with headless Chrome first.
- Render the finished PDF to page images (PyMuPDF in a throwaway venv) and **look at every slide** before publishing. Known pitfalls: callout titles that wrap and overlap the body (size the title box from its length), `**` inside text eaten by bold-markup parsing, section titles wrapping into subtitles, two-digit numbers wrapping inside small circles.

## PHASE 8: Verify, then ask before publishing

1. Run the offline tests; run the pipeline on both documents in both modes; run the scorer; re-run the limit tests and re-render evidence.
2. Re-read the README against the fresh results. Fix every stale number.
3. `git status` shows no `.env` and no keys in any file (`grep` the tree for key-looking strings).
4. Then **ask the user** before creating the GitHub repo (private) and pushing. Commit messages end with the attribution line the environment specifies.

## FINAL REPORT FORMAT

When done, tell the user: what was built, what was measured (with ranges), what contradicted the documentation or expectations, what you could not verify, and what is still design-only. Lead with the findings that change decisions (for example the truncation behavior), not with a file list.

## KNOWN OPEN ITEMS (state them, do not hide them)

- No document **classification** stage exists (statement vs dispute form vs authorization). Mention it as a gap. If the user wants it, options are Document Intelligence custom classification and Language custom text classification; verify current limits before quoting any. Classification must never decide whether a page is scanned (fail-open risk): use it for policy and routing only.
- Document Intelligence reading a blob via URL (instead of uploading bytes) is target design only.
- Entra ID (keyless) auth is not implemented in the code.
- Scanned PDFs, handwriting, and non-English text are untested.
