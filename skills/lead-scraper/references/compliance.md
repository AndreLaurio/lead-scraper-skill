# Compliance and etiquette

Lead generation from public business data is normal and legal in most places, but
the line between "public business contact" and "personal data" matters, and so does
how you fetch. This skill is built to stay on the right side of both.

## What this skill collects

- Business names, websites, business phone numbers, generic and role emails
  (`info@`, `hello@`, `dr.smith@acmedental.com` published on the practice's own site),
  social profile URLs the company itself links to, addresses, tech stack.
- Everything comes from the company's own website or OpenStreetMap. Nothing is
  taken from behind a login, from LinkedIn, from Facebook pages, or from data brokers.

## What it deliberately does not do

- No scraping of individuals' profiles, personal emails or phone numbers.
- No LinkedIn, Facebook, Instagram, Google Maps, Yelp page scraping. Their terms
  forbid it and they actively ban for it. Only the URL of a company's profile is
  recorded, taken from the company's own site.
- No bypassing of bot protection, CAPTCHAs, or robots.txt. A 403 means "not welcome";
  the lead keeps whatever OSM knew and moves on.
- No identity spoofing: the User-Agent names this tool and links to the repo.
  Overriding it (`--user-agent`) is for testing your own sites.

## Rate limits built in

- 1 request/second per host, 3 pages per site by default, 6 sites in parallel.
- Nominatim: 1 req/s (their published policy). Overpass: one query per run, with a
  60 s server-side timeout; the script never loops over Overpass automatically.
- Keep `--workers` under ~10; faster is not noticeably faster and gets you blocked.

## Using the leads

- **GDPR / UK GDPR**: B2B outreach to a role address is generally fine under
  legitimate interest; emailing a named person still requires a legitimate-interest
  assessment, an easy opt-out, and honoring it. Keep the `sources` column so you can
  answer "where did you get my details".
- **CAN-SPAM (US)**: commercial email needs a real postal address, a working
  unsubscribe, and honest subject lines. No consent requirement, but no deception.
- **CASL (Canada)**: stricter; implied consent for B2B is narrow. Phone first.
- **TCPA (US)**: do not auto-dial or text numbers from this list.
- Never resell the list as a dataset. It is for your own outreach.

If a user asks for something outside these lines (personal data, LinkedIn profiles,
evading a block), say which line it crosses in one sentence and offer the compliant
version of the task.
