#!/usr/bin/env python3
"""Verify a CJV-MTH-1.0 register without trusting the issuer.

Usage:
    python verify_register.py [register.json]

The script recomputes every record hash from the canonical payload and prints the
head hash, so anyone can check that a published register is internally consistent
and that its head matches what was cited.

No dependencies. Python 3.8+.
"""
import json
import os
import sys


def fnv1a(text: str) -> str:
    """FNV-1a, 32-bit, over UTF-8 code points of `text` (see specification 10.2)."""
    h = 0x811C9DC5
    for ch in text:
        h ^= ord(ch)
        h = (h * 0x01000193) & 0xFFFFFFFF
    return f"{h:08x}"


def grade(metered_share: float) -> str:
    if metered_share >= 70.0:
        return "A"
    if metered_share >= 45.0:
        return "B"
    return "C"


def verify(doc: dict) -> int:
    labels = doc.get("labels", [])
    failures = []

    prev = "genesis"
    for i, rec in enumerate(labels, 1):
        # 6.2 / 10.1 — canonical payload
        expected_payload = f"{rec['batch']}|{rec['kgco2e_total']}|{rec['kgco2e_per_unit']}|{rec['grade']}"
        if rec.get("payload") != expected_payload:
            failures.append((i, "payload", rec.get("payload"), expected_payload))

        # 10.3 — chain
        if rec.get("prev") != prev:
            failures.append((i, "prev", rec.get("prev"), prev))
        expected_hash = fnv1a(prev + expected_payload)
        if rec.get("hash") != expected_hash:
            failures.append((i, "hash", rec.get("hash"), expected_hash))

        # 6.3 — arithmetic invariants
        if rec.get("units"):
            per_unit = rec["kgco2e_total"] / rec["units"]
            if abs(per_unit - rec["kgco2e_per_unit"]) > 0.001:
                failures.append((i, "per_unit", rec["kgco2e_per_unit"], round(per_unit, 3)))
        if rec.get("baseline_per_unit"):
            red = (1 - rec["kgco2e_per_unit"] / rec["baseline_per_unit"]) * 100
            if abs(red - rec.get("reduction_pct", 0)) > 0.2:
                failures.append((i, "reduction_pct", rec.get("reduction_pct"), round(red, 1)))

        # 7 — grade matches metered share
        if "data_quality" in rec:
            if grade(rec["data_quality"]) != rec.get("grade"):
                failures.append((i, "grade", rec.get("grade"), grade(rec["data_quality"])))

        prev = expected_hash

    print(f"  records:        {len(labels)}")
    print(f"  declared head:  {doc.get('head')}")
    print(f"  recomputed head:{prev}")
    print(f"  method:         {doc.get('method')} / {doc.get('method_hash')}")

    if failures:
        print(f"\n  FAILED — {len(failures)} problem(s):")
        for i, field, got, expected in failures[:20]:
            print(f"    record {i} {field}: got {got!r}, expected {expected!r}")
        return 1

    if doc.get("head") and doc["head"] != prev:
        print("\n  FAILED — head hash does not match the chain")
        return 1

    print("\n  OK — payload, chain, arithmetic and grades all verify")
    return 0


def main() -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(here, "register-labels.json")
    if not os.path.exists(path):
        print(f"  register not found: {path}")
        return 2
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    print(f"  file:           {os.path.basename(path)}")
    return verify(doc)


if __name__ == "__main__":
    raise SystemExit(main())
