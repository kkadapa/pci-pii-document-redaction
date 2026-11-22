"""
Scores pipeline output against the ground truth from generate_banking_pdf.py.

For each label in the cardholder blocks, it reads the value that follows the label in
the masked text and counts it as leaked if it exactly matches a planted value. This avoids
false positives from short values (such as a 3-digit CVV) appearing elsewhere on the page.

Usage (from the project root):
  python scripts/score_results.py <pipeline output json> [ground truth json]
"""

import json
import re
import sys

FIELDS = {
    "Cardholder:": "name",
    "Email:": "email",
    "Phone:": "phone",
    "SSN on file:": "ssn",
    "Card number:": "card_number",
    "Expiration:": "expiry",
    "CVV:": "cvv",
}
NEXT_LABEL = "|".join(re.escape(label) for label in FIELDS) + r"|Card type:|Date\b"


def score(result_path, truth_path):
    masked = json.load(open(result_path))["masked_text"]
    planted = json.load(open(truth_path))["planted"]

    print(f"{'Field':12s} {'Labels found':>12s} {'Leaked':>8s}")
    for label, field in FIELDS.items():
        truth = {p[field] for p in planted}
        pattern = re.compile(re.escape(label) + r"\s*(.+?)\s*(?=" + NEXT_LABEL + r"|\n|$)")
        values = [m.group(1) for m in pattern.finditer(masked)]
        leaked = sum(1 for v in values if v in truth)
        print(f"{field:12s} {len(values):12d} {leaked:5d}/{len(planted)}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/score_results.py <output json> [ground truth json]", file=sys.stderr)
        sys.exit(2)
    score(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "test_data/ground_truth_500p.json")
