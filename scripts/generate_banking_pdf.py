"""
Generates a realistic synthetic batch of monthly credit card statements as one PDF, plus a
ground-truth file listing every planted PCI/PII value and its page.

What the document looks like:
  - One statement per customer: an account summary page, 1-4 transaction pages, an
    interest and fees page, and a disclosures page.
  - Ordinary pages show card numbers already masked, as real statements do
    ("Card ending in 1111", "XXXX XXXX XXXX 1111").
  - Full card data (number, expiry, CVV) appears only on occasional attached forms:
    card dispute forms, payment authorizations, and balance transfer requests. About one
    statement in five has one, at irregular positions in the batch.

All data is fictional: card numbers are public test numbers, names and addresses are made
up, and SSNs are well-known example numbers that are not issued to real people.

Usage (from the project root):
  python scripts/generate_banking_pdf.py                 # 500 pages, into test_data/
  python scripts/generate_banking_pdf.py --pages 2000    # 2,000 pages

Output: banking_statements_<N>p.pdf and ground_truth_<N>p.json
"""

import argparse
import json
import os
import random
import textwrap

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

SEED = 42
FORM_PROBABILITY = 0.2
ROWS_PER_TRANSACTION_PAGE = 28

# Public test card numbers: valid format and checksum, not real accounts
TEST_CARDS = [
    ("Visa", "4111 1111 1111 1111"), ("Visa", "4012 8888 8888 1881"), ("Visa", "4242 4242 4242 4242"),
    ("Mastercard", "5555 5555 5555 4444"), ("Mastercard", "5105 1051 0510 5100"),
    ("American Express", "3782 822463 10005"), ("American Express", "3714 496353 98431"),
    ("Discover", "6011 1111 1111 1117"), ("Discover", "6011 0009 9013 9424"),
]
# Widely published example SSNs that the Social Security Administration never issues to people
EXAMPLE_SSNS = ["123-45-6789", "078-05-1120", "219-09-9999"]

FIRST = ["Mateo", "Ava", "Liam", "Sofia", "Noah", "Maya", "Ethan", "Priya", "Omar", "Lena",
         "Grace", "Daniel", "Aisha", "Lucas", "Hannah", "Kenji", "Elena", "Marcus", "Zara", "Owen"]
LAST = ["Gomez", "Chen", "Patel", "Okafor", "Schmidt", "Rossi", "Nakamura", "Silva", "Brown", "Haddad",
        "Kowalski", "Nguyen", "Fischer", "Moreau", "Larsen", "Costa", "Ibrahim", "Walsh", "Kim", "Duarte"]
STREETS = ["Maple Avenue", "Oak Street", "Cedar Lane", "Harbor Drive", "Willow Court", "Sunset Boulevard",
           "Pine Ridge Road", "Lakeview Terrace", "Elm Street", "Mission Street"]
CITIES = [("Seattle", "WA", "98101"), ("Austin", "TX", "78701"), ("Denver", "CO", "80202"),
          ("Boston", "MA", "02108"), ("Chicago", "IL", "60601"), ("Atlanta", "GA", "30303"),
          ("Phoenix", "AZ", "85004"), ("Portland", "OR", "97204")]
MERCHANTS = [
    ("CONTOSO GROCERY", "SEATTLE WA"), ("FABRIKAM FUEL", "AUSTIN TX"), ("NORTHWIND COFFEE", "DENVER CO"),
    ("ADVENTURE WORKS OUTDOOR", "BOSTON MA"), ("LITWARE ELECTRONICS", "CHICAGO IL"),
    ("TAILSPIN PHARMACY", "ATLANTA GA"), ("WOODGROVE BOOKS", "PORTLAND OR"), ("BLUE YONDER AIRLINES", "PHOENIX AZ"),
    ("ALPINE SKI HOUSE", "DENVER CO"), ("COHO WINERY", "SEATTLE WA"), ("MARGIE'S TRAVEL", "BOSTON MA"),
    ("PROSEWARE UTILITIES", "AUSTIN TX"), ("WINGTIP TOYS", "CHICAGO IL"), ("TREY RESEARCH LABS", "ATLANTA GA"),
    ("FOURTH COFFEE", "PORTLAND OR"), ("WIDE WORLD IMPORTERS", "PHOENIX AZ"),
]
DISCLOSURE = (
    "Important information about your account. Interest charges: we charge interest on purchases from the "
    "transaction date unless you pay your New Balance in full by the Payment Due Date each month. Your due date "
    "is at least 25 days after the close of each billing cycle. Annual Percentage Rate (APR) for purchases: "
    "21.49%. APR for balance transfers: 21.49%. APR for cash advances: 27.49%. Penalty APR: up to 29.99%, which "
    "may apply if you make a late payment. Minimum interest charge: if you are charged interest, the charge will "
    "be no less than $1.00. Fees: balance transfer fee, either $5 or 3% of the amount of each transfer, whichever "
    "is greater. Cash advance fee, either $10 or 5% of the amount of each advance, whichever is greater. Foreign "
    "transaction fee: 3% of each transaction in U.S. dollars. Late payment fee: up to $40. Returned payment fee: "
    "up to $40. How we calculate your balance: we use a method called average daily balance (including new "
    "purchases). Billing rights: if you think there is an error on your statement, write to us at Northwind Bank, "
    "Billing Inquiries, P.O. Box 1000, Seattle, WA 98111, within 60 days after the error appeared on your "
    "statement. In your letter, give us your name, the last four digits of your account number, the dollar amount "
    "of the suspected error, and a description of the problem. While we investigate, we cannot try to collect the "
    "amount in question or report you as delinquent on that amount. Payments: send payments to Northwind Bank, "
    "P.O. Box 2000, Seattle, WA 98112. Payments received by 5 p.m. Pacific time on a business day are credited "
    "that day. This statement is synthetic test data. No real account, card, or customer is represented."
)


def build_statements(rng, total_pages):
    """Plan every page: a list of (kind, customer, data) tuples, trimmed to exactly total_pages."""
    pages, planted = [], []
    stmt_no = 0
    while len(pages) < total_pages:
        stmt_no += 1
        first, last = rng.choice(FIRST), rng.choice(LAST)
        city, state, zipc = rng.choice(CITIES)
        card_type, card_no = rng.choice(TEST_CARDS)
        customer = {
            "name": f"{first} {last}",
            "address": f"{rng.randrange(100, 9999)} {rng.choice(STREETS)}, {city}, {state} {zipc}",
            "account_last4": f"{rng.randrange(1000, 9999)}",
            "card_type": card_type, "card_no": card_no, "last4": card_no.replace(" ", "")[-4:],
            "limit": rng.choice([5000, 7500, 10000, 15000, 20000]),
            "previous": round(rng.uniform(200, 3000), 2),
            "stmt_no": stmt_no,
        }
        txns = []
        for _ in range(rng.randrange(20, ROWS_PER_TRANSACTION_PAGE * 4)):
            merchant, loc = rng.choice(MERCHANTS)
            txns.append((f"10/{rng.randrange(1, 31):02d}", f"{merchant} {loc}",
                         f"{rng.randrange(10**9, 10**10)}", round(rng.uniform(4, 480), 2)))
        txns.sort()
        txns.insert(0, ("10/03", "PAYMENT - THANK YOU", f"{rng.randrange(10**9, 10**10)}",
                        -round(rng.uniform(100, 2500), 2)))
        pages.append(("summary", customer, txns))
        for i in range(0, len(txns), ROWS_PER_TRANSACTION_PAGE):
            pages.append(("transactions", customer, txns[i:i + ROWS_PER_TRANSACTION_PAGE]))
        pages.append(("fees", customer, None))
        pages.append(("disclosures", customer, None))
        if rng.random() < FORM_PROBABILITY:
            form_type = rng.choice(["Card Dispute Form", "Recurring Payment Authorization", "Balance Transfer Request"])
            cvv = f"{rng.randrange(1000, 9999)}" if card_type == "American Express" else f"{rng.randrange(100, 999)}"
            pages.append(("form", customer, {
                "form_type": form_type,
                "name": customer["name"],
                "email": f"{first.lower()}.{last.lower()}{stmt_no}@example-mail.test",
                "phone": f"{rng.choice(['206', '512', '303', '617', '312', '404', '602', '503'])}-555-{rng.randrange(1000, 9999):04d}",
                "ssn": rng.choice(EXAMPLE_SSNS),
                "card_number": card_no,
                "expiry": f"{rng.randrange(1, 13):02d}/{rng.randrange(27, 33):02d}",
                "cvv": cvv,
            }))
    pages = pages[:total_pages]
    for i, (kind, _, data) in enumerate(pages, start=1):
        if kind == "form":
            planted.append({"page": i, **data})
    return pages, planted, stmt_no


def header(c, customer, page_no, total, title):
    w, h = letter
    c.setFont("Helvetica-Bold", 14)
    c.drawString(54, h - 54, "Northwind Bank")
    c.setFont("Helvetica", 9)
    c.drawString(54, h - 68, "Credit card services  |  northwindbank.example  |  1-800-555-0100")
    c.drawRightString(w - 54, h - 54, title)
    c.drawRightString(w - 54, h - 68, f"Statement period 10/01/2026 - 10/31/2026   Page {page_no} of {total}")
    c.drawRightString(w - 54, h - 80, f"Card ending in {customer['last4']}")
    c.line(54, h - 88, w - 54, h - 88)


def draw_summary(c, customer, txns, page_no, total):
    w, h = letter
    header(c, customer, page_no, total, "Credit Card Statement")
    purchases = sum(t[3] for t in txns if t[3] > 0)
    payments = -sum(t[3] for t in txns if t[3] < 0)
    previous = customer["previous"]
    interest = round(previous * 0.0179, 2)
    new_balance = round(previous - payments + purchases + interest, 2)
    y = h - 115
    c.setFont("Helvetica-Bold", 11)
    c.drawString(54, y, customer["name"].upper())
    c.setFont("Helvetica", 10)
    c.drawString(54, y - 14, customer["address"])
    c.drawString(54, y - 40, f"Account number: XXXX XXXX {customer['account_last4']}")
    c.drawString(54, y - 54, f"{customer['card_type']} card number: XXXX XXXX XXXX {customer['last4']}")
    rows = [("Previous balance", previous), ("Payments and credits", -payments), ("Purchases", purchases),
            ("Fees charged", 0.00), ("Interest charged", interest), ("New balance", new_balance)]
    y -= 95
    c.setFont("Helvetica-Bold", 11)
    c.drawString(54, y, "Account summary")
    c.setFont("Helvetica", 10)
    for label, amount in rows:
        y -= 16
        c.drawString(64, y, label)
        c.drawRightString(330, y, f"${amount:,.2f}")
    y -= 30
    c.setFont("Helvetica-Bold", 11)
    c.drawString(54, y, "Payment information")
    c.setFont("Helvetica", 10)
    c.drawString(64, y - 16, f"New balance: ${new_balance:,.2f}")
    c.drawString(64, y - 32, f"Minimum payment due: ${max(35, round(new_balance * 0.02, 2)):,.2f}")
    c.drawString(64, y - 48, "Payment due date: 11/25/2026")
    c.drawString(64, y - 64, f"Credit limit: ${customer['limit']:,.2f}   Available credit: ${customer['limit'] - new_balance:,.2f}")
    c.setFont("Helvetica", 8.5)
    for i, line in enumerate(textwrap.wrap(
            "Late payment warning: if we do not receive your minimum payment by the date listed above, you may "
            "have to pay a late fee of up to $40 and your APRs may be increased up to the Penalty APR of 29.99%.", 110)):
        c.drawString(54, 120 - i * 11, line)


def draw_transactions(c, customer, txns, page_no, total):
    w, h = letter
    header(c, customer, page_no, total, "Transactions")
    y = h - 115
    c.setFont("Helvetica-Bold", 9.5)
    c.drawString(54, y, "Date")
    c.drawString(100, y, "Description")
    c.drawString(390, y, "Reference")
    c.drawRightString(w - 54, y, "Amount")
    c.setFont("Helvetica", 9.5)
    for date, desc, ref, amount in txns:
        y -= 20
        c.drawString(54, y, date)
        c.drawString(100, y, desc[:46])
        c.drawString(390, y, ref)
        c.drawRightString(w - 54, y, f"{amount:,.2f}")


def draw_fees(c, customer, page_no, total):
    w, h = letter
    header(c, customer, page_no, total, "Interest and Fees")
    y = h - 120
    c.setFont("Helvetica-Bold", 11)
    c.drawString(54, y, "Interest charge calculation")
    c.setFont("Helvetica", 10)
    for label, apr, bal in [("Purchases", "21.49%", 1840.22), ("Balance transfers", "21.49%", 0.00),
                            ("Cash advances", "27.49%", 0.00)]:
        y -= 18
        c.drawString(64, y, f"{label}: APR {apr}, balance subject to interest rate ${bal:,.2f}, 31 days in billing cycle")
    y -= 36
    c.setFont("Helvetica-Bold", 11)
    c.drawString(54, y, "Totals year to date")
    c.setFont("Helvetica", 10)
    c.drawString(64, y - 18, "Total fees charged in 2026: $0.00")
    c.drawString(64, y - 36, "Total interest charged in 2026: $214.67")


def draw_disclosures(c, customer, page_no, total):
    w, h = letter
    header(c, customer, page_no, total, "Important Information")
    c.setFont("Helvetica", 9.5)
    y = h - 115
    for line in textwrap.wrap(DISCLOSURE, 108):
        c.drawString(54, y, line)
        y -= 13


def draw_form(c, customer, form, page_no, total):
    w, h = letter
    header(c, customer, page_no, total, form["form_type"])
    y = h - 120
    c.setFont("Helvetica-Bold", 13)
    c.drawString(54, y, form["form_type"])
    c.setFont("Helvetica", 10)
    intro = {
        "Card Dispute Form": "I am disputing the charge listed below. Please investigate and credit my account.",
        "Recurring Payment Authorization": "I authorize Northwind Bank to charge the card below each month for my loan payment.",
        "Balance Transfer Request": "Please transfer the balance below to my Northwind Bank card account.",
    }[form["form_type"]]
    c.drawString(54, y - 22, intro)
    fields = [("Cardholder", form["name"]), ("Email", form["email"]), ("Phone", form["phone"]),
              ("SSN on file", form["ssn"]), ("Card type", customer["card_type"]),
              ("Card number", form["card_number"]), ("Expiration", form["expiry"]), ("CVV", form["cvv"])]
    y -= 60
    for label, value in fields:
        c.drawString(64, y, f"{label}: {value}")
        y -= 20
    c.drawString(64, y - 20, "Amount: $249.99        Merchant: LITWARE ELECTRONICS CHICAGO IL")
    c.drawString(64, y - 60, "Signature: ______________________________        Date: 10/28/2026")


def build_pdf(output_dir, total_pages):
    rng = random.Random(SEED)
    pages, planted, statements = build_statements(rng, total_pages)
    os.makedirs(output_dir, exist_ok=True)
    pdf_path = os.path.join(output_dir, f"banking_statements_{total_pages}p.pdf")
    truth_path = os.path.join(output_dir, f"ground_truth_{total_pages}p.json")

    c = canvas.Canvas(pdf_path, pagesize=letter, invariant=1)
    c.setTitle("Northwind Bank synthetic credit card statements (test data)")
    for page_no, (kind, customer, data) in enumerate(pages, start=1):
        if kind == "summary":
            draw_summary(c, customer, data, page_no, total_pages)
        elif kind == "transactions":
            draw_transactions(c, customer, data, page_no, total_pages)
        elif kind == "fees":
            draw_fees(c, customer, page_no, total_pages)
        elif kind == "disclosures":
            draw_disclosures(c, customer, page_no, total_pages)
        else:
            draw_form(c, customer, data, page_no, total_pages)
        c.showPage()
    c.save()

    kinds = {}
    for kind, _, _ in pages:
        kinds[kind] = kinds.get(kind, 0) + 1
    with open(truth_path, "w", encoding="utf-8") as f:
        json.dump({"total_pages": total_pages, "statements": statements, "page_types": kinds,
                   "planted": planted}, f, indent=2)
    return pdf_path, truth_path, planted, kinds, statements


if __name__ == "__main__":
    default_out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "test_data")
    parser = argparse.ArgumentParser(description="Generate synthetic credit card statements")
    parser.add_argument("--pages", type=int, default=500, help="number of pages (default 500)")
    parser.add_argument("--out", default=default_out, help="output folder (default test_data/)")
    args = parser.parse_args()
    pdf, truth, planted, kinds, statements = build_pdf(args.out, args.pages)
    print(f"PDF: {pdf}\nGround truth: {truth}")
    print(f"Statements: {statements}  Page types: {kinds}  Form pages with full card data: {len(planted)}")
