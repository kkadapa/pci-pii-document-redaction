# Team walkthrough deck

A 32-slide walkthrough of the whole project, for presenting to the team:

| File | Use |
|------|-----|
| [`pci-pii-redaction-walkthrough.pptx`](pci-pii-redaction-walkthrough.pptx) | Editable deck for PowerPoint, Keynote, or Google Slides. Every slide has speaker notes |
| [`pci-pii-redaction-walkthrough.pdf`](pci-pii-redaction-walkthrough.pdf) | Same deck as PDF. GitHub previews it in the browser |

| Part | Slides | Covers |
|------|--------|--------|
| 1. The problem and the result | 3–5 | Goal, scope, and the outcome on one slide |
| 2. The pipeline, and how we got here | 6–9 | The 8 pipeline steps, the project timeline, and what broke along the way |
| 3. Test results | 10–14 | Test documents, detection accuracy, over-masking, processing time (including per-page figures) |
| 4. Service limits, tested live | 15–21 | Documented limits, what happened when each was exceeded, the silent-truncation finding, screenshots, design takeaways |
| 5. Target architecture and next steps | 22–32 | Both architecture diagrams, request flow, design decisions, mask or block, an honest readiness assessment, known gaps, recommendations, next steps |

Every number on the slides comes from the main [README](../../README.md) and the transcripts in [`docs/evidence/logs/`](../evidence/logs/).

## Rebuilding

The deck is generated, so edit `scripts/build_presentation.py` rather than the PPTX, then run from the project root:

```
python scripts/build_presentation.py
```

This needs `python-pptx`, Google Chrome (to render the SVG diagrams), and LibreOffice for the PDF copy. Without LibreOffice, only the PPTX is written.
