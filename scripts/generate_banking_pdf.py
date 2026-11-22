"""
Generates a synthetic banking statement PDF (500 pages by default) for load and accuracy
testing, plus a ground-truth manifest listing every planted PII/PCI value and its page.
A cardholder block is planted on every 20th page.

All names, accounts, and card numbers are fake. Card numbers are public test numbers.

Usage (from the project root):
  python scripts/generate_banking_pdf.py                 # 500 pages, into test_data/
  python scripts/generate_banking_pdf.py --pages 2000    # 2,000 pages
  python scripts/generate_banking_pdf.py --pages 2000 --out some_dir

Output: banking_statements_<N>p.pdf and ground_truth_<N>p.json
"""

import json
import os
import random

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

TOTAL_PAGES = 500  # overridden by --pages
PLANT_EVERY = 20  # pages 20, 40, 60, ... get a card block
SEED = 42

# Public test card numbers (valid format, not real accounts)
TEST_CARDS = [
    ("Visa", "4111 1111 1111 1111"),
    ("Mastercard", "5555 5555 5555 4444"),
    ("American Express", "3782 822463 10005"),
    ("Discover", "6011 1111 1111 1117"),
]

FIRST_NAMES = ["Mateo", "Ava", "Liam", "Sofia", "Noah", "Maya", "Ethan", "Priya", "Omar", "Lena"]
LAST_NAMES = ["Gomez", "Chen", "Patel", "Okafor", "Schmidt", "Rossi", "Nakamura", "Silva", "Brown", "Haddad"]
MERCHANTS = [
    "Contoso Restaurant", "Fabrikam Grocery", "Northwind Fuel", "Adventure Works Travel",
    "Litware Electronics", "Tailspin Pharmacy", "Woodgrove Books", "Proseware Utilities",
    "Alpine Ski House", "Blue Yonder Airlines", "Coho Winery", "Margie's Travel",
]


def build_plan(rng):
    """Create per-page plan: which page gets which planted PII, recorded for ground truth."""
    plan = {}
    manifest = []
    for page in range(PLANT_EVERY, TOTAL_PAGES + 1, PLANT_EVERY):
        first = rng.choice(FIRST_NAMES)
        last = rng.choice(LAST_NAMES)
        card_type, card_no = TEST_CARDS[rng.randrange(len(TEST_CARDS))]
        cvv = f"{rng.randrange(100, 999)}" if card_type != "American Express" else f"{rng.randrange(1000, 9999)}"
        exp_month = rng.randrange(1, 13)
        exp_year = rng.randrange(27, 33)
        expiry = f"{exp_month:02d}/{exp_year:02d}"
        email = f"{first.lower()}.{last.lower()}{page}@example-mail.test"
        phone = f"949-555-{rng.randrange(1000, 9999):04d}"
        ssn = f"000-{rng.randrange(10, 99)}-{rng.randrange(1000, 9999)}"  # 000 area is never issued
        plan[page] = {
            "name": f"{first} {last}",
            "card_type": card_type,
            "card_number": card_no,
            "cvv": cvv,
            "expiry": expiry,
            "email": email,
            "phone": phone,
            "ssn": ssn,
        }
        manifest.append({"page": page, **plan[page]})
    return plan, manifest


def build_pdf(output_dir):
    rng = random.Random(SEED)
    plan, manifest = build_plan(rng)

    os.makedirs(output_dir, exist_ok=True)
    pdf_path = os.path.join(output_dir, f"banking_statements_{TOTAL_PAGES}p.pdf")
    manifest_path = os.path.join(output_dir, f"ground_truth_{TOTAL_PAGES}p.json")

    styles = getSampleStyleSheet()
    title = styles["Heading2"]
    body = styles["BodyText"]
    body.fontSize = 9
    body.leading = 11

    story = []
    for page in range(1, TOTAL_PAGES + 1):
        acct_num = f"0000{rng.randrange(10**8, 10**9)}"
        story.append(Paragraph(f"Account Statement - Account {acct_num}", title))
        story.append(Paragraph(f"Statement page {page} of {TOTAL_PAGES}. Period: 01 Oct 2026 to 31 Oct 2026.", body))
        story.append(Spacer(1, 8))

        if page in plan:
            p = plan[page]
            story.append(Paragraph("<b>Cardholder and payment details</b>", body))
            story.append(Paragraph(
                f"Cardholder: {p['name']}<br/>"
                f"Email: {p['email']}<br/>"
                f"Phone: {p['phone']}<br/>"
                f"SSN on file: {p['ssn']}<br/>"
                f"Card type: {p['card_type']}<br/>"
                f"Card number: {p['card_number']}<br/>"
                f"Expiration: {p['expiry']}<br/>"
                f"CVV: {p['cvv']}",
                body,
            ))
            story.append(Spacer(1, 10))

        rows = [["Date", "Description", "Amount (USD)", "Balance (USD)"]]
        balance = round(rng.uniform(1000, 9000), 2)
        for _ in range(18):
            amount = round(rng.uniform(-250, 250), 2)
            balance = round(balance + amount, 2)
            day = rng.randrange(1, 29)
            rows.append([
                f"2026-10-{day:02d}",
                rng.choice(MERCHANTS),
                f"{amount:,.2f}",
                f"{balance:,.2f}",
            ])
        table = Table(rows, colWidths=[80, 230, 100, 100])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
        ]))
        story.append(table)
        story.append(Spacer(1, 10))
        story.append(Paragraph(
            "This statement is synthetic test data. No real account, card, or customer is represented.",
            body,
        ))
        if page < TOTAL_PAGES:
            story.append(PageBreak())

    doc = SimpleDocTemplate(pdf_path, pagesize=letter, leftMargin=54, rightMargin=54, topMargin=54, bottomMargin=54)
    doc.build(story)

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump({"total_pages": TOTAL_PAGES, "planted": manifest}, f, indent=2)

    return pdf_path, manifest_path, len(manifest)


if __name__ == "__main__":
    import argparse
    default_out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "test_data")
    parser = argparse.ArgumentParser(description="Generate a synthetic bank statement PDF")
    parser.add_argument("--pages", type=int, default=500, help="number of pages (default 500)")
    parser.add_argument("--out", default=default_out, help="output folder (default test_data/)")
    args = parser.parse_args()
    TOTAL_PAGES = args.pages
    out = args.out
    pdf, man, n = build_pdf(out)
    print(f"PDF: {pdf}\nManifest: {man}\nPlanted blocks: {n}")
