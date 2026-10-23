#!/usr/bin/env python3
"""Merge, dedupe and score lead CSVs from any source into one clean file.

Rows are matched on domain (from `website`/`domain`), else on normalized
company name. Later files fill blanks left by earlier ones; `emails`/`phones`
style columns are unioned. Each lead gets a 0-100 `score` so you can sort by
contactability. Standard library only.

Usage:
  merge_leads.py seeds.csv enriched.csv --output leads.csv
  merge_leads.py a.csv b.csv -o leads.csv --min-score 40 --require email
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
import urllib.parse
from typing import Dict, List, Optional

MULTI = ("emails", "phones", "tech", "sources")
ALIASES = {"url": "website", "site": "website", "email": "emails", "phone": "phones", "name": "company_name",
           "company": "company_name", "source": "sources"}
PREFERRED_ORDER = ["company_name", "website", "domain", "emails", "phones", "linkedin", "twitter", "facebook",
                   "instagram", "youtube", "address", "city", "postcode", "category", "title", "description",
                   "tech", "score", "sources"]
SUFFIXES = (" inc", " llc", " ltd", " limited", " gmbh", " co", " corp", " corporation", " plc", " sa", " srl")


def norm_domain(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    host = urllib.parse.urlsplit(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def norm_name(name: str) -> str:
    n = re.sub(r"[^a-z0-9 ]", " ", (name or "").lower())
    n = re.sub(r"\s+", " ", n).strip()
    for s in SUFFIXES:
        if n.endswith(s):
            n = n[: -len(s)].strip()
    return n


def split_multi(v: str) -> List[str]:
    return [x.strip() for x in re.split(r"[;,|]", v or "") if x.strip()]


def multi_key(col: str, value: str) -> str:
    """Dedupe key for multi-valued cells: phones compare by their last 10 digits
    so '+1-512-474-7575' and '5124747575' collapse into one."""
    if col == "phones":
        return re.sub(r"\D", "", value)[-10:]
    return value.lower()


def score(row: Dict[str, str]) -> int:
    s = 0
    emails = split_multi(row.get("emails", ""))
    domain = row.get("domain", "")
    if emails:
        s += 35
        if any(e.endswith("@" + domain) for e in emails) and domain:
            s += 10
        if any(not re.match(r"^(info|contact|hello|office|admin|support|sales|mail|team)@", e) for e in emails):
            s += 10  # a named person's inbox beats a generic one
    if split_multi(row.get("phones", "")):
        s += 20
    if row.get("website") and not row.get("error"):
        s += 10
    if row.get("linkedin"):
        s += 10
    if row.get("address") or row.get("city"):
        s += 5
    return min(s, 100)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+", help="CSV files, earliest takes precedence for scalar fields")
    ap.add_argument("--output", "-o", required=True)
    ap.add_argument("--min-score", type=int, default=0)
    ap.add_argument("--require", choices=["email", "phone", "any"], help="Drop leads lacking this contact method")
    ap.add_argument("--drop-errors", action="store_true", help="Drop rows whose website could not be fetched")
    args = ap.parse_args()

    merged: Dict[str, Dict[str, str]] = {}
    order: List[str] = []
    for path in args.inputs:
        with open(path, newline="", encoding="utf-8") as f:
            for raw in csv.DictReader(f):
                row = {}
                for k, v in raw.items():
                    if k is None:
                        continue
                    key = ALIASES.get(k.strip().lower(), k.strip().lower())
                    v = (v or "").strip()
                    if key in row and row[key]:
                        if key in MULTI and v:
                            row[key] = row[key] + "; " + v
                        continue
                    row[key] = v
                row.setdefault("sources", path)
                dom = norm_domain(row.get("website", "")) or row.get("domain", "")
                if dom:
                    row["domain"] = dom
                key = ("d:" + dom) if dom else ("n:" + norm_name(row.get("company_name", "")))
                if key in ("d:", "n:"):
                    continue
                if key not in merged:
                    merged[key] = row
                    order.append(key)
                    continue
                target = merged[key]
                for k, v in row.items():
                    if not v:
                        continue
                    if k in MULTI:
                        existing = split_multi(target.get(k, ""))
                        keys = {multi_key(k, e) for e in existing}
                        for item in split_multi(v):
                            if multi_key(k, item) not in keys:
                                existing.append(item)
                                keys.add(multi_key(k, item))
                        target[k] = "; ".join(existing)
                    elif not target.get(k):
                        target[k] = v

    rows = [merged[k] for k in order]
    for r in rows:
        r["score"] = str(score(r))
    if args.drop_errors:
        rows = [r for r in rows if not r.get("error")]
    if args.require == "email":
        rows = [r for r in rows if r.get("emails")]
    elif args.require == "phone":
        rows = [r for r in rows if r.get("phones")]
    elif args.require == "any":
        rows = [r for r in rows if r.get("emails") or r.get("phones")]
    rows = [r for r in rows if int(r["score"]) >= args.min_score]
    rows.sort(key=lambda r: (-int(r["score"]), r.get("company_name", "").lower()))

    all_cols = {k for r in rows for k in r}
    cols = [c for c in PREFERRED_ORDER if c in all_cols] + sorted(all_cols - set(PREFERRED_ORDER))
    with open(args.output, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    n_email = sum(1 for r in rows if r.get("emails"))
    n_phone = sum(1 for r in rows if r.get("phones"))
    print(f"{len(rows)} leads ({n_email} with email, {n_phone} with phone) -> {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
