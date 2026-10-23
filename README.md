# lead-scraper — a Claude Code skill for building B2B lead lists

Tell Claude *"find me 100 dentists in Austin with emails"* or *"enrich these 200 domains
with contact info"* and get back a scored CSV. Public business data only, polite by
design, zero Python dependencies.

```
leads-dentists-austin.csv — 112 leads
  87 with email (61 on their own domain), 104 with phone, 23 with LinkedIn
  Sources: OpenStreetMap (96), web search (31); 15 duplicates merged
```

## What it does

1. **Discover** companies matching a niche + place from OpenStreetMap (free, no API key),
   or from web search for online-only niches (SaaS, ecommerce, agencies).
2. **Enrich** each company website: emails, phones, LinkedIn / X / Facebook / Instagram /
   YouTube, title, description, tech stack (Shopify, WordPress, HubSpot…).
3. **Merge, dedupe, score** (0–100 contactability) and export a CSV ready for a CRM.

Everything runs locally with Python 3.9+ standard library. Rate-limited, honors
`robots.txt`, identifies itself honestly. See
[`skills/lead-scraper/references/compliance.md`](skills/lead-scraper/references/compliance.md)
for what is and is not collected.

## Install

**As a Claude Code plugin (recommended)**

Inside Claude Code:

```
/plugin install lead-scraper --marketplace AndreLaurio/lead-scraper-skill
```

**Or copy the skill folder**

```bash
git clone https://github.com/AndreLaurio/lead-scraper-skill
mkdir -p ~/.claude/skills
cp -r lead-scraper-skill/skills/lead-scraper ~/.claude/skills/
```

Then in Claude Code: `/lead-scraper find 50 plumbers in Manchester with phone numbers`,
or just ask in plain language; the skill triggers on lead / prospect / contact-list requests.

## Use the scripts without Claude

```bash
cd skills/lead-scraper
python3 scripts/find_businesses.py --what "coffee shop" --near "Lisbon, Portugal" --limit 200 -o seeds.csv
python3 scripts/enrich_websites.py -i seeds.csv -o enriched.csv
python3 scripts/merge_leads.py seeds.csv enriched.csv -o leads.csv --require any
python3 scripts/find_businesses.py --list-categories
```

| Script | Purpose |
|---|---|
| `find_businesses.py` | Geocode a place (Nominatim), query Overpass for a business category, output name/website/phone/email/address |
| `enrich_websites.py` | Crawl homepage + contact/about pages per site (3 pages, 1 req/s/host), extract contact details |
| `merge_leads.py` | Union any lead CSVs on domain, dedupe phones/emails, score, filter (`--require email`, `--min-score 50`) |

## Limits worth knowing

- OpenStreetMap coverage is excellent in Europe, good in big US cities, thin in rural
  areas. The skill falls back to web search when a query comes back short.
- 10–20 % of sites sit behind bot protection and return 403. Those leads keep whatever
  OSM knew (usually phone, sometimes email) and are not retried with a fake browser.
- Public Overpass servers are shared; a query takes 10–60 s. Be kind with `--limit`.

## Repo layout

```
.claude-plugin/plugin.json        plugin manifest
skills/lead-scraper/
  SKILL.md                        the workflow Claude follows
  scripts/                        find_businesses.py, enrich_websites.py, merge_leads.py
  references/                     search recipes, OSM tag guide, compliance notes
  evals/                          test cases runnable with `claude plugin eval`
```

## License

MIT. OpenStreetMap data is © OpenStreetMap contributors, ODbL.
