# Service limit evidence

Screenshots of live tests against Azure AI Document Intelligence (`idpdocgta`, S0) and Azure AI Language (`idpgtalangll`, S tier), run on November 22, 2026 (US Pacific; the transcripts' timestamps are UTC).

The results, and what they mean for the design, are explained in the main README: [Service limit evidence](../../README.md#service-limit-evidence).

| File | Test | Result |
|------|------|--------|
| `00-test-document-sample-pages.png` | Four pages of the 500-page test batch | Account summary, transactions, disclosures, and a card dispute form |
| `01-document-intelligence-2001-pages.png` | 2,001-page PDF sent to Document Intelligence | Accepted and reported as succeeded, but only 2,000 pages analyzed: silent truncation |
| `02-document-intelligence-501-mb.png` | 501 MiB upload | `400 InvalidContentLength` after 160 KB |
| `03-document-intelligence-rate-limit-429.png` | 60 analyze requests, 30 in parallel | 25 refused with `429`, `Retry-After: 1` |
| `04-language-5120-characters.png` | 6,000-character document | `InvalidDocument` for that document; the other one processed |
| `05-language-6-documents-sync.png` | 6 documents, synchronous | `400 InvalidDocumentBatch` |
| `06-language-26-documents-async.png` | 26 documents, asynchronous | `400 InvalidDocumentBatch` |
| `07-language-125000-characters-async.png` | 127,500 characters, asynchronous | `413` (documentation says `400`) |
| `08-language-rate-limit-429.png` | 1,100 requests, 40 in parallel | 505 refused with `429`, `Retry-After: 45` |
| `09-pipeline-precheck-rejections.png` | This pipeline's pre-check on a 2,001-page and a 501 MiB file | Both rejected before any Azure call |
| `10-pipeline-results-500-and-2000-pages.png` | Scoring of the 500- and 2,000-page runs, and block mode | All card data masked; 1 name missed at 2,000 pages; block mode blocked |

- **How the screenshots are made:** `scripts/test_service_limits.py` runs the tests and writes the plain-text transcripts in [`logs/`](logs/). `scripts/render_evidence.py` renders them as images, adding only colors and layout.
- **What the transcripts contain:** no keys and no document content.
- **Dropped connections:** the "connection error (SSLError)" lines are TLS handshake failures on the test machine's network, not service responses.
