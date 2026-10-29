"""Shared data loading, PHI label map and metrics for the edge-medicine benchmark.

Metrics are label-agnostic (what matters for de-identification is whether the
characters of an identifier get masked), computed at character and entity level.
"""
from __future__ import annotations

import hashlib
import json
import re

# HIPAA Safe Harbor identifiers (45 CFR 164.514(b)(2)) mapped to Nemotron-PII labels.
PHI = {
    "first_name", "last_name", "medical_record_number", "date_of_birth", "date",
    "date_time", "health_plan_beneficiary_number", "email", "phone_number",
    "fax_number", "biometric_identifier", "street_address", "city", "county",
    "postcode", "coordinate", "certificate_license_number", "url", "ipv4", "ipv6",
    "credit_debit_card", "account_number", "bank_routing_number", "employee_id",
    "national_id", "ssn", "tax_id", "unique_id", "customer_id", "mac_address",
    "user_name", "license_plate", "vehicle_identifier", "device_identifier",
    # Gretel pii-masking label names
    "name", "address", "credit_card_number", "unique_identifier", "medical_record_number",
}
# Secrets that are not Safe Harbor identifiers but must never reach a model.
SECRETS = {"password", "pin", "cvv", "api_key", "http_cookie", "swift_bic"}

# Clinical measurements that a de-identifier must leave intact (utility).
CLINICAL = re.compile(
    r"\b\d{1,3}(?:[.,]\d+)?(?:/\d{1,3})?\s?(?:mmHg|mg/dL|mmol/L|bpm|mg|mcg|µg|g/dL|mL|kg|lbs?|"
    r"°[CF]|%|IU|units?|breaths/min|kcal|steps|hours?|hrs?)\b",
    re.IGNORECASE,
)


def load(path):
    with open(path, encoding="utf8") as f:
        for line in f:
            yield json.loads(line)


def partition(uid: str, k: int = 3) -> int:
    return int(hashlib.sha256(uid.split("_")[0].encode()).hexdigest(), 16) % k


def _cover(spans, n):
    m = bytearray(n)
    for s, e in spans:
        m[max(0, s):min(n, e)] = b"\x01" * (min(n, e) - max(0, s))
    return m


class Score:
    """Accumulates character- and entity-level counts over documents."""

    def __init__(self):
        self.c = dict(phi_chars=0, phi_hit=0, pred_chars=0, pred_in_gold=0,
                      ent=0, ent_full=0, ent_any=0, sec_chars=0, sec_hit=0,
                      clin=0, clin_kept=0, docs=0)
        self.by_label = {}

    def add(self, text, gold, pred):
        n = len(text)
        c = self.c
        c["docs"] += 1
        pm = _cover(pred, n)
        allg = _cover([(g["start"], g["end"]) for g in gold], n)
        for g in gold:
            s, e, lab = g["start"], g["end"], g["label"]
            hit = sum(pm[s:e])
            ln = e - s
            if lab in PHI:
                c["phi_chars"] += ln
                c["phi_hit"] += hit
                c["ent"] += 1
                c["ent_full"] += hit == ln
                c["ent_any"] += hit > 0
                b = self.by_label.setdefault(lab, [0, 0])
                b[0] += 1
                b[1] += hit == ln
            elif lab in SECRETS:
                c["sec_chars"] += ln
                c["sec_hit"] += hit
        c["pred_chars"] += sum(pm)
        c["pred_in_gold"] += sum(1 for i in range(n) if pm[i] and allg[i])
        for m in CLINICAL.finditer(text):
            s, e = m.span()
            if any(allg[s:e]):
                continue
            c["clin"] += 1
            c["clin_kept"] += not any(pm[s:e])

    def result(self):
        c = self.c
        rec = c["phi_hit"] / max(1, c["phi_chars"])
        prec = c["pred_in_gold"] / max(1, c["pred_chars"])
        f2 = 5 * prec * rec / max(1e-9, 4 * prec + rec)
        return dict(
            docs=c["docs"], char_recall=rec, char_precision=prec, char_f2=f2,
            entity_recall_full=c["ent_full"] / max(1, c["ent"]),
            entity_recall_any=c["ent_any"] / max(1, c["ent"]),
            secret_recall=c["sec_hit"] / max(1, c["sec_chars"]),
            clinical_preserved=c["clin_kept"] / max(1, c["clin"]), clinical_n=c["clin"],
            phi_entities=c["ent"],
        )

    def label_table(self):
        return {k: (v[0], v[1] / max(1, v[0])) for k, v in sorted(self.by_label.items(), key=lambda x: -x[1][0])}
