#!/usr/bin/env python3
"""Enrich a list of company websites with public contact details.

Reads website URLs (one per line, or a CSV with a `website` column), fetches
the homepage plus the usual contact/about pages, and extracts:

  emails, phones, LinkedIn / Twitter(X) / Facebook / Instagram / YouTube URLs,
  page title, meta description, detected tech hints (Shopify, WordPress, ...).

Honors robots.txt, sends a descriptive User-Agent, rate-limits per host,
and never follows off-site links. Standard library only (Python 3.9+).

Usage:
  enrich_websites.py --input seeds.csv --output leads.csv
  enrich_websites.py --input urls.txt --output leads.csv --workers 8 --max-pages 4
  echo "https://example.com" | enrich_websites.py --output leads.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
from typing import Dict, Iterable, List, Optional, Set, Tuple

USER_AGENT = (
    "lead-scraper-skill/1.0 (+https://github.com/AndreLaurio/lead-scraper-skill; "
    "public business contact discovery; contact via repo issues)"
)
DATE_RE = re.compile(r"^\d{4}[-./]\d{1,2}[-./]\d{1,2}$|^\d{1,2}[-./]\d{1,2}[-./]\d{4}$")
TIMEOUT = 12
CONTACT_HINTS = ("contact", "about", "team", "kontakt", "impressum", "get-in-touch", "reach")
MAX_BYTES = 1_500_000

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# Loose international phone matcher; results are post-filtered by digit count.
PHONE_RE = re.compile(r"(?:\+?\d[\d\s().-]{7,}\d)")
JUNK_EMAIL_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".css", ".js")
JUNK_EMAIL_PARTS = ("example.com", "sentry", "wixpress", "@2x", "domain.com", "email.com", "yourdomain")
SOCIAL_PATTERNS = {
    "linkedin": re.compile(r"https?://(?:[a-z]{2,3}\.)?linkedin\.com/(?:company|in|school)/[^\s\"'<>?#]+", re.I),
    "twitter": re.compile(r"https?://(?:www\.)?(?:twitter|x)\.com/[A-Za-z0-9_]{1,15}(?![A-Za-z0-9_])", re.I),
    "facebook": re.compile(r"https?://(?:www\.)?facebook\.com/[^\s\"'<>?#]+", re.I),
    "instagram": re.compile(r"https?://(?:www\.)?instagram\.com/[A-Za-z0-9_.]+", re.I),
    "youtube": re.compile(r"https?://(?:www\.)?youtube\.com/(?:@|c/|channel/|user/)[^\s\"'<>?#]+", re.I),
}
SOCIAL_JUNK = ("/sharer", "/share", "/intent/", "/login", "/signup", "/home", "/plugins/", "/dialog/")
TECH_HINTS = {
    "shopify": ("cdn.shopify.com", "myshopify.com"),
    "wordpress": ("wp-content", "wp-includes"),
    "wix": ("wix.com", "wixstatic"),
    "squarespace": ("squarespace.com",),
    "webflow": ("webflow.io", "webflow.com"),
    "hubspot": ("hs-scripts.com", "hubspot.com"),
    "google-analytics": ("googletagmanager.com", "google-analytics.com"),
    "intercom": ("intercom.io", "intercomcdn"),
    "stripe": ("js.stripe.com",),
    "calendly": ("calendly.com",),
}


class PageParser(HTMLParser):
    """Collects links, title, meta description and mailto/tel hrefs."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: List[str] = []
        self.mailtos: Set[str] = set()
        self.tels: Set[str] = set()
        self.title = ""
        self.description = ""
        self._in_title = False
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        a = dict(attrs)
        if tag == "title":
            self._in_title = True
        elif tag == "meta":
            name = (a.get("name") or a.get("property") or "").lower()
            if name in ("description", "og:description") and a.get("content") and not self.description:
                self.description = a["content"].strip()
        elif tag == "a" and a.get("href"):
            href = a["href"].strip()
            low = href.lower()
            if low.startswith("mailto:"):
                self.mailtos.add(href[7:].split("?")[0].strip())
            elif low.startswith("tel:"):
                self.tels.add(href[4:].strip())
            else:
                self.links.append(href)
        elif tag in ("script", "style"):
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        elif tag in ("script", "style") and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._in_title and not self._skip_depth:
            self.title += data


class HostThrottle:
    """Minimum spacing between requests to the same host."""

    def __init__(self, min_interval: float) -> None:
        self.min_interval = min_interval
        self._last: Dict[str, float] = {}

    def wait(self, host: str) -> None:
        last = self._last.get(host)
        if last is not None:
            delta = time.monotonic() - last
            if delta < self.min_interval:
                time.sleep(self.min_interval - delta)
        self._last[host] = time.monotonic()


def normalize_url(raw: str) -> Optional[str]:
    raw = raw.strip()
    if not raw:
        return None
    if not re.match(r"^https?://", raw, re.I):
        raw = "https://" + raw
    parts = urllib.parse.urlsplit(raw)
    if not parts.netloc or "." not in parts.netloc:
        return None
    return urllib.parse.urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path or "/", "", ""))


def domain_of(url: str) -> str:
    host = urllib.parse.urlsplit(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


HAVE_CURL = shutil.which("curl") is not None


def _fetch_curl(url: str, any_type: bool = False) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Fallback for Pythons linked against old LibreSSL (macOS system python)
    that fail the TLS handshake on many modern sites."""
    cmd = ["curl", "-sS", "-L", "-m", str(TIMEOUT * 2), "-A", USER_AGENT, "--max-filesize", str(MAX_BYTES),
           "-w", "\\n%{url_effective}\\n%{content_type}\\n%{http_code}", "-o", "-", url]
    proc = subprocess.run(cmd, capture_output=True, check=False)
    if proc.returncode != 0:
        return None, None, f"curl: {proc.stderr.decode(errors='replace').strip()[:100]}"
    out = proc.stdout.decode("utf-8", errors="replace")
    body, _, trailer = out.rpartition("\n")
    body, _, ctype = body.rpartition("\n")
    body, _, final = body.rpartition("\n")
    if not trailer.startswith("2"):
        return None, None, f"http {trailer}"
    if not any_type and ctype and "html" not in ctype and "xml" not in ctype:
        return final, None, f"non-html content-type: {ctype}"
    return final, body, None


def fetch(url: str, accept: str = "text/html,*/*;q=0.5", any_type: bool = False
          ) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Returns (final_url, body, error)."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            ctype = resp.headers.get("Content-Type", "")
            if not any_type and "html" not in ctype and "xml" not in ctype and ctype:
                return resp.geturl(), None, f"non-html content-type: {ctype}"
            body = resp.read(MAX_BYTES)
            charset = resp.headers.get_content_charset() or "utf-8"
            return resp.geturl(), body.decode(charset, errors="replace"), None
    except urllib.error.HTTPError as e:
        return None, None, f"http {e.code}"
    except urllib.error.URLError as e:
        if "SSL" in str(e).upper() and HAVE_CURL:
            return _fetch_curl(url, any_type)
        return None, None, f"{type(e).__name__}: {e}"[:120]
    except Exception as e:  # noqa: BLE001 - we want to keep going on any network failure
        if "SSL" in type(e).__name__.upper() and HAVE_CURL:
            return _fetch_curl(url, any_type)
        return None, None, f"{type(e).__name__}: {e}"[:120]


def robots_allowed(base: str, path: str, cache: Dict[str, Optional[urllib.robotparser.RobotFileParser]]) -> bool:
    host = urllib.parse.urlsplit(base).netloc
    if host not in cache:
        # Fetch robots.txt ourselves: RobotFileParser.read() uses the default
        # "Python-urllib" agent, which bot-protection often answers with 403, and
        # the parser then treats the whole site as disallowed. A missing or
        # erroring robots.txt means "no restrictions", per the de-facto standard.
        _, text, err = fetch(urllib.parse.urljoin(base, "/robots.txt"), accept="text/plain,*/*;q=0.5", any_type=True)
        if text is None or err:
            cache[host] = None
        else:
            rp = urllib.robotparser.RobotFileParser()
            try:
                rp.parse(text.splitlines())
                cache[host] = rp
            except Exception:  # noqa: BLE001
                cache[host] = None
    rp = cache[host]
    if rp is None:
        return True
    try:
        return rp.can_fetch(USER_AGENT, path) and rp.can_fetch("*", path)
    except Exception:  # noqa: BLE001
        return True


def clean_emails(found: Iterable[str], domain: str) -> List[str]:
    out: Set[str] = set()
    for e in found:
        e = e.strip().strip(".").lower()
        if e.endswith(JUNK_EMAIL_SUFFIXES) or any(j in e for j in JUNK_EMAIL_PARTS):
            continue
        if len(e) > 80:
            continue
        out.add(e)
    # Prefer emails on the company's own domain first, then the rest.
    own = sorted(e for e in out if e.endswith("@" + domain) or e.endswith("." + domain))
    other = sorted(out - set(own))
    return own + other


def looks_like_phone(p: str) -> bool:
    """Heuristic for regex-found numbers (tel: links are trusted and skip this).
    Bare digit runs are usually ids (Facebook pixel ids, timestamps), so a real
    phone needs 2-5 digit groups separated by spaces, dots, dashes or parens."""
    if "." in p and not re.search(r"\d\.\d{3}\.\d", p):
        return False
    groups = [g for g in re.split(r"[\s().-]+", p.strip()) if g]
    if not 2 <= len(groups) <= 6:
        return False
    first = groups[0].lstrip("+")
    if len(first) < 2 and not groups[0].startswith("+") and first != "1":
        return False  # "8-7166-4510-85" is an id; "1-800-..." is a phone
    for g in groups[1:]:
        if not g.isdigit() or not 2 <= len(g) <= 8:
            return False
    return first.isdigit() and 1 <= len(first) <= 5


def clean_phones(trusted: Iterable[str], found: Iterable[str]) -> List[str]:
    out: List[str] = []
    seen: Set[str] = set()
    for p, is_trusted in [(t, True) for t in trusted] + [(f, False) for f in found]:
        p = re.sub(r"\s+", " ", p.strip())
        digits = re.sub(r"\D", "", p)
        if not (8 <= len(digits) <= 15) or len(set(digits)) <= 2 or DATE_RE.match(p):
            continue
        if not is_trusted and not looks_like_phone(p):
            continue
        key = digits[-10:]
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out[:5]


def extract_socials(html: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for name, pat in SOCIAL_PATTERNS.items():
        for m in pat.finditer(html):
            url = m.group(0).rstrip("/.,)")
            if any(j in url.lower() for j in SOCIAL_JUNK):
                continue
            out[name] = url
            break
    return out


def detect_tech(html: str) -> List[str]:
    low = html.lower()
    return [name for name, needles in TECH_HINTS.items() if any(n in low for n in needles)]


def company_name_from_title(title: str, domain: str) -> str:
    """'Dentist in Austin | Aloha Dental' -> 'Aloha Dental'. Sites put the brand
    on either side of the separator, so pick the segment that shares the most
    letters with the domain name; fall back to the first segment."""
    if not title:
        return domain
    segments = [seg.strip() for seg in re.split(r"\s+[|\-–—:·»]\s+", title) if seg.strip()]
    if not segments:
        return title[:120]
    stem = re.sub(r"[^a-z0-9]", "", domain.split(".")[0])
    def overlap(seg: str) -> int:
        compact = re.sub(r"[^a-z0-9]", "", seg.lower())
        if not compact or not stem:
            return 0
        if compact in stem or stem in compact:
            return 100
        return sum(1 for w in re.findall(r"[a-z0-9]{3,}", seg.lower()) if w in stem)
    best = max(segments, key=overlap)
    return (best if overlap(best) > 0 else segments[0])[:120]


def pick_contact_links(base: str, links: Iterable[str], limit: int) -> List[str]:
    base_domain = domain_of(base)
    picked: List[str] = []
    seen: Set[str] = set()
    for href in links:
        full = urllib.parse.urljoin(base, href)
        full = full.split("#")[0]
        if domain_of(full) != base_domain:
            continue
        path = urllib.parse.urlsplit(full).path.lower()
        if not any(h in path for h in CONTACT_HINTS):
            continue
        if full in seen or full.rstrip("/") == base.rstrip("/"):
            continue
        seen.add(full)
        picked.append(full)
        if len(picked) >= limit:
            break
    return picked


def enrich_one(url: str, max_pages: int, throttle: HostThrottle, robots_cache: Dict) -> Dict[str, str]:
    row: Dict[str, str] = {
        "website": url,
        "domain": domain_of(url),
        "company_name": "",
        "title": "",
        "description": "",
        "emails": "",
        "phones": "",
        "linkedin": "",
        "twitter": "",
        "facebook": "",
        "instagram": "",
        "youtube": "",
        "tech": "",
        "pages_fetched": "0",
        "error": "",
    }
    host = urllib.parse.urlsplit(url).netloc
    if not robots_allowed(url, "/", robots_cache):
        row["error"] = "blocked by robots.txt"
        return row

    throttle.wait(host)
    final_url, html, err = fetch(url)
    if html is None:
        # Retry once over http if https failed at the transport layer.
        if url.startswith("https://") and err and not err.startswith("http "):
            alt = "http://" + url[len("https://"):]
            throttle.wait(host)
            final_url, html, err = fetch(alt)
        if html is None:
            row["error"] = err or "no content"
            return row

    base = final_url or url
    row["website"] = base
    row["domain"] = domain_of(base)
    emails: Set[str] = set()
    tels: List[str] = []
    phones: List[str] = []
    socials: Dict[str, str] = {}
    tech: Set[str] = set()
    fetched = 1

    parser = PageParser()
    try:
        parser.feed(html)
    except Exception:  # noqa: BLE001 - malformed HTML is common
        pass
    row["title"] = re.sub(r"\s+", " ", parser.title).strip()[:200]
    row["description"] = re.sub(r"\s+", " ", parser.description).strip()[:300]
    emails.update(parser.mailtos)
    emails.update(EMAIL_RE.findall(html))
    tels.extend(parser.tels)
    phones.extend(PHONE_RE.findall(re.sub(r"<[^>]+>", " ", html)))
    socials.update(extract_socials(html))
    tech.update(detect_tech(html))

    for link in pick_contact_links(base, parser.links, max_pages - 1):
        path = urllib.parse.urlsplit(link).path or "/"
        if not robots_allowed(base, path, robots_cache):
            continue
        throttle.wait(host)
        _, sub_html, _ = fetch(link)
        if not sub_html:
            continue
        fetched += 1
        sub = PageParser()
        try:
            sub.feed(sub_html)
        except Exception:  # noqa: BLE001
            pass
        emails.update(sub.mailtos)
        emails.update(EMAIL_RE.findall(sub_html))
        tels.extend(sub.tels)
        phones.extend(PHONE_RE.findall(re.sub(r"<[^>]+>", " ", sub_html)))
        for k, v in extract_socials(sub_html).items():
            socials.setdefault(k, v)

    row["company_name"] = company_name_from_title(row["title"], row["domain"])
    row["emails"] = "; ".join(clean_emails(emails, row["domain"])[:5])
    row["phones"] = "; ".join(clean_phones(tels, phones))
    for k in ("linkedin", "twitter", "facebook", "instagram", "youtube"):
        row[k] = socials.get(k, "")
    row["tech"] = "; ".join(sorted(tech))
    row["pages_fetched"] = str(fetched)
    return row


def read_inputs(path: Optional[str]) -> List[Tuple[str, Dict[str, str]]]:
    """Returns (url, extra_columns) pairs. Extra columns from a CSV are carried through."""
    stream = open(path, newline="", encoding="utf-8") if path else sys.stdin
    try:
        text = stream.read()
    finally:
        if path:
            stream.close()
    lines = [l for l in text.splitlines() if l.strip()]
    if not lines:
        return []
    header = lines[0].lower()
    if "," in header and ("website" in header or "url" in header):
        reader = csv.DictReader(lines)
        col = next((c for c in reader.fieldnames or [] if c.lower() in ("website", "url", "site", "domain")), None)
        out = []
        for r in reader:
            u = normalize_url(r.get(col, "") if col else "")
            if u:
                extras = {k: v for k, v in r.items() if k != col and v}
                out.append((u, extras))
        return out
    return [(u, {}) for u in (normalize_url(l) for l in lines) if u]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", "-i", help="CSV with a website/url column, or a text file of URLs. Default: stdin")
    ap.add_argument("--output", "-o", required=True, help="Output CSV path (use .jsonl for JSON lines)")
    ap.add_argument("--workers", type=int, default=6, help="Parallel sites (default 6)")
    ap.add_argument("--max-pages", type=int, default=3, help="Pages per site incl. homepage (default 3)")
    ap.add_argument("--delay", type=float, default=1.0, help="Min seconds between hits on one host (default 1.0)")
    ap.add_argument("--limit", type=int, default=0, help="Only process the first N sites (0 = all)")
    ap.add_argument("--user-agent", help="Override the User-Agent header (default identifies this tool)")
    args = ap.parse_args()
    if args.user_agent:
        global USER_AGENT
        USER_AGENT = args.user_agent

    items = read_inputs(args.input)
    if args.limit:
        items = items[: args.limit]
    if not items:
        print("no input URLs found", file=sys.stderr)
        return 1

    # Dedupe by domain up front so we never hammer one site twice.
    seen: Set[str] = set()
    unique: List[Tuple[str, Dict[str, str]]] = []
    for u, extra in items:
        d = domain_of(u)
        if d in seen:
            continue
        seen.add(d)
        unique.append((u, extra))

    throttle = HostThrottle(args.delay)
    robots_cache: Dict = {}
    results: List[Dict[str, str]] = []
    print(f"enriching {len(unique)} sites with {args.workers} workers...", file=sys.stderr)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(enrich_one, u, args.max_pages, throttle, robots_cache): (u, extra) for u, extra in unique}
        done = 0
        for fut in as_completed(futs):
            u, extra = futs[fut]
            try:
                row = fut.result()
            except Exception as e:  # noqa: BLE001
                row = {"website": u, "domain": domain_of(u), "error": f"{type(e).__name__}: {e}"[:120]}
            for k, v in extra.items():
                row.setdefault(k, v)
                if not row.get(k):
                    row[k] = v
            results.append(row)
            done += 1
            status = row.get("error") or f"{len(row.get('emails','').split('; ')) if row.get('emails') else 0} emails"
            print(f"[{done}/{len(unique)}] {row.get('domain')}: {status}", file=sys.stderr)

    results.sort(key=lambda r: (r.get("error", "") != "", r.get("domain", "")))
    base_cols = ["company_name", "website", "domain", "emails", "phones", "linkedin", "twitter", "facebook",
                 "instagram", "youtube", "title", "description", "tech", "pages_fetched", "error"]
    extra_cols = sorted({k for r in results for k in r} - set(base_cols))
    cols = base_cols + extra_cols

    if args.output.endswith(".jsonl"):
        with open(args.output, "w", encoding="utf-8") as f:
            for r in results:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    else:
        with open(args.output, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            w.writerows(results)

    ok = sum(1 for r in results if not r.get("error"))
    with_email = sum(1 for r in results if r.get("emails"))
    with_phone = sum(1 for r in results if r.get("phones"))
    print(f"done: {ok}/{len(results)} reachable, {with_email} with email, {with_phone} with phone -> {args.output}",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
