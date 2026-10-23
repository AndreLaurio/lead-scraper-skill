# Web discovery recipes (for niches OpenStreetMap does not cover)

Use the WebSearch tool (or WebFetch on a directory page) to collect company
**domains**, then write them to a CSV with a `website` column and hand it to
`enrich_websites.py`. Searching is the slow, judgment-heavy part; enrichment is
mechanical. Spend your effort on query variety, not on reading each site.

## Query patterns that produce company lists fast

| Goal | Query shape |
|---|---|
| Directory pages (one page = dozens of leads) | `"top" OR "best" <niche> <city>` then WebFetch the listicle and pull the outbound links |
| Review platforms | `site:clutch.co <niche> <city>`, `site:g2.com <category>`, `site:trustpilot.com <niche>` |
| Chambers / associations | `<city> chamber of commerce members <niche>`, `<niche> association member directory` |
| Job boards reveal active companies | `site:linkedin.com/jobs <role> <city>` is off limits (ToS) but `site:indeed.com <niche> <city>` or `site:wellfound.com <niche>` is fine |
| Tech-based targeting | `"powered by shopify" <product keyword>`, `site:myshopify.com <keyword>`, `"built with webflow" <niche>` |
| Agencies / studios | `<service> agency <city> -jobs -reddit`, `"we are a" <niche> agency` |
| Ecommerce brands | `<product> "free shipping" "add to cart" -amazon -ebay -etsy` |
| Funding / growth signals | `site:techcrunch.com OR site:prnewswire.com "<niche>" raised` |
| Local but missing from OSM | `<niche> near <neighborhood>` and collect the business sites, not the aggregator |

Run 5-10 varied queries rather than one; each surfaces a different slice. Dedupe by
domain as you go. Skip aggregators (Yelp, Yellow Pages, Google Maps links, Facebook
pages) as *leads*, but do open a directory page once to harvest the real sites it links to.

## Turning search results into a seed CSV

```csv
company_name,website,category,city,source
Acme Dental,https://acmedental.com,dentist,Austin,websearch:"best dentist austin"
```

`company_name` can be blank; the enricher derives it from the site title. Keep a
`source` column with the query so the final summary can say where leads came from.

## When to stop searching

Stop when either you have 1.5x the requested count of unique domains, or three
consecutive queries add fewer than 3 new domains. Diminishing returns set in fast;
the user would rather get 80 good leads now than 120 in twice the time.
