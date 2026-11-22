"""Probe which PCI/PII values the Language REST API detects, per API version. Test data only."""

import json
import os

import requests
from dotenv import load_dotenv

load_dotenv()
ENDPOINT = os.environ["AZURE_LANGUAGE_ENDPOINT"].rstrip("/")
KEY = os.environ["AZURE_LANGUAGE_KEY"]

TEXTS = {
    "card_block": "Card type: Visa. Card number: 4111 1111 1111 1111. Expiration: 04/28. CVV: 123.",
    "ssn_000_prefix": "SSN on file: 000-96-9935",
    "ssn_valid_format": "SSN on file: 123-45-6789",
}

CATEGORIES = ["CreditCardNumber", "CVV", "ExpirationDate", "USSocialSecurityNumber",
              "Email", "PhoneNumber", "Person"]


def call(api_version, pii_categories=None):
    body = {
        "kind": "PiiEntityRecognition",
        "analysisInput": {"documents": [
            {"id": k, "language": "en", "text": v} for k, v in TEXTS.items()
        ]},
        "parameters": {"modelVersion": "latest"},
    }
    if pii_categories:
        body["parameters"]["piiCategories"] = pii_categories
    r = requests.post(
        f"{ENDPOINT}/language/:analyze-text",
        params={"api-version": api_version},
        headers={"Ocp-Apim-Subscription-Key": KEY, "Content-Type": "application/json"},
        json=body,
        timeout=60,
    )
    if r.status_code != 200:
        return {"http_status": r.status_code, "error": r.text[:300]}
    out = {}
    for doc in r.json()["results"]["documents"]:
        out[doc["id"]] = {
            "entities": [(e["category"], e["text"]) for e in doc["entities"]],
            "redacted": doc["redactedText"],
        }
    return out


for label, version, cats in [
    ("GA 2026-05-01, default categories", "2026-05-01", None),
    ("Preview 2026-05-15-preview, explicit categories", "2026-05-15-preview", CATEGORIES),
]:
    print(f"=== {label}")
    print(json.dumps(call(version, cats), indent=1))
