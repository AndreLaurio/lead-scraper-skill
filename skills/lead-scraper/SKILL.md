---
name: lead-scraper
description: >-
  Build B2B lead lists from public sources: find companies that match an ideal customer
  profile (industry/niche + location or online), pull their website, emails, phones,
  socials and address, dedupe and score them, and deliver a clean CSV ready for a CRM or
  outreach tool. Use this whenever the user wants leads, prospects, a prospect list, a
  contact list, "companies that do X in Y", local business lists, "find me dentists in
  Austin with emails", agency/SaaS/ecommerce target lists, or wants to enrich a list of
  domains with contact info, even if they never say "scrape". Not for scraping
  individuals' personal data, LinkedIn profiles, or sites behind a login.
compatibility: Python 3.9+ (standard library only, no pip installs); curl is used as a TLS fallback on macOS system Python. Internet access required.
---

# Lead Scraper

Turn "I need leads for X in Y" into a scored CSV of companies with contact details.
Only public business information is collected (company sites, OpenStreetMap). Read
`references/compliance.md` once before the first run in a session: it explains what is
fine to collect, what is not, and why the scripts are deliberately polite (rate limits,
robots.txt, honest User-Agent). Those limits are what keep this usable long term.

## Workflow

### 1. Pin down the ICP (ideal customer profile)

You need four things. Infer what you can from the request and ask only for what is
genuinely missing; a user who says "dentists in Austin" has already given you three.

| Field | Example | Default if unstated |
|---|---|---|
| Who | dentists, Shopify stores selling pet food, SaaS with 10-50 staff | ask |
| Where | Austin TX, Portugal, online/global | ask if the niche is physical |
| How many | 50, 500 | 100 |
| Must-have | email, phone, LinkedIn | email or phone |

State the plan in one line before running anything ("Finding ~100 dentists around
Austin from OpenStreetMap, enriching each site for emails/phones, output `leads-dentists-austin.csv`").

### 2. Discover companies (pick the source by lead type)

**Physical / local businesses** (clinics, trades, restaurants, agencies with an office):
use OpenStreetMap. Free, no key, returns name, website, phone, address.

```bash
python3 scripts/find_businesses.py --what dentist --near "Austin, TX" --limit 300 -o seeds.csv
python3 scripts/find_businesses.py --list-categories          # 70+ built-in categories
python3 scripts/find_businesses.py --tag office=lawyer --near "Lisbon" -o seeds.csv   # raw OSM tag
```

Expect 10-60 s per query; the public Overpass servers are shared. If a city returns too
few results, widen with `--radius-km 40`, try a sibling category (`clinic` as well as
`doctor`), or run the query for several nearby towns and merge. Coverage varies by
region: OSM is strong in Europe, decent in large US cities, thin in rural areas. When
OSM gives fewer than about half of what the user asked for, add web discovery below.

**Online / niche / B2B companies** (SaaS, ecommerce brands, agencies, "companies using
Shopify that sell X"): OSM will not have them. Use the WebSearch tool with the query
recipes in `references/search-recipes.md` (directory sites, "site:" patterns, review
platforms, job boards) and collect company domains into a CSV with a `website` column
plus any columns you already know (`company_name`, `category`, `city`). Aim for 1.5x
the requested count because enrichment loses some to dead sites and bot walls.

Keep every seed CSV. The merge step unions them.

### 3. Enrich each website

```bash
python3 scripts/enrich_websites.py -i seeds.csv -o enriched.csv --workers 6 --max-pages 3
```

Fetches homepage + contact/about pages, extracts emails (mailto and text), phones,
LinkedIn/X/Facebook/Instagram/YouTube, title, meta description and tech hints
(Shopify, WordPress, HubSpot...). Throughput is roughly 1-2 sites/s with 6 workers,
so 300 sites is 3-5 minutes; run in the background for anything over ~100 and tell the
user the ETA. A `--limit 10` dry run first is a cheap way to confirm the seed list is
sane before spending the full time.

Rows with `error` = `http 403` or `blocked by robots.txt` are sites that refused a
bot. Leave them; do not retry with a browser User-Agent unless the user explicitly
asks and understands the site asked not to be crawled.

### 4. Merge, dedupe, score, deliver

```bash
python3 scripts/merge_leads.py seeds.csv enriched.csv -o leads-dentists-austin.csv --require any
```

Matches on domain (fallback: normalized name), unions emails/phones, and adds a 0-100
`score` (email 35, own-domain email +10, named person's inbox +10, phone 20, live
site 10, LinkedIn 10, address 5). `--require email|phone|any` and `--min-score N`
filter. Output is sorted by score. Name the file `leads-<niche>-<place>.csv`.

Finish with a short summary the user can act on:

```
leads-dentists-austin.csv — 112 leads
  87 with email (61 on their own domain), 104 with phone, 23 with LinkedIn
  Sources: OpenStreetMap (96), web search (31); 15 duplicates merged
  Skipped: 9 sites blocked bots, 4 unreachable
  Top 3: Aloha Dental (score 90), Canvas Dental (85), KC Dental (85)
```

Mention anything that shaped the result (thin OSM coverage, a category that needed a
raw tag) so the user can decide whether to widen the search.

## Enriching a list the user already has

If the user brings a CSV or a list of domains, skip discovery: run step 3 on it (the
script accepts a CSV with any `website`/`url`/`domain` column and carries the other
columns through), then step 4 with the original file first so their columns win.

## Things that go wrong

- **Few OSM results**: the category word is not an OSM tag. Check `--list-categories`
  or `references/osm-categories.md`; pass `--tag key=value`. Some businesses are tagged
  only under a parent (`healthcare=*`, `office=company`).
- **Overpass timeouts / 504**: the server is busy. The script rotates three mirrors and
  retries; if all fail, wait a minute and rerun with a smaller `--limit` or `--radius-km`.
- **Many 403s**: Cloudflare-style bot protection. Expected for 10-20% of sites. The
  OSM phone/email still gets merged in, so these leads are not lost, just thinner.
- **Garbage phones/emails**: the extractor already filters dates, coordinates, image
  names and tracking ids. If something odd slips through, drop that value rather than
  loosening the filters for everyone.
- **macOS system Python SSL errors**: handled automatically by falling back to curl.

## Files

- `scripts/find_businesses.py` — OSM discovery (Nominatim geocode + Overpass query)
- `scripts/enrich_websites.py` — polite site crawler, contact extraction
- `scripts/merge_leads.py` — merge / dedupe / score / filter
- `references/search-recipes.md` — WebSearch query patterns for non-local niches
- `references/osm-categories.md` — how OSM tags map to business types
- `references/compliance.md` — what is OK to collect, rate limits, GDPR/CAN-SPAM basics
