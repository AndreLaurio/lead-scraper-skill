#!/usr/bin/env python3
"""Find local businesses by category and area using OpenStreetMap (free, no API key).

Geocodes the area with Nominatim, then queries the Overpass API for matching
businesses and writes name / website / phone / email / address / coordinates.
Standard library only (Python 3.9+).

Usage:
  find_businesses.py --what dentist --near "Austin, TX" --output seeds.csv
  find_businesses.py --what "coffee shop" --near "Lisbon, Portugal" --limit 200
  find_businesses.py --tag office=accountant --near "Manchester, UK"
  find_businesses.py --list-categories

OSM data is ODbL licensed: keep the attribution ("© OpenStreetMap contributors")
if you publish the output. Overpass is a shared community server: keep
--limit reasonable and do not run this in a tight loop.
"""
from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, List, Optional, Tuple

USER_AGENT = "lead-scraper-skill/1.0 (+https://github.com/AndreLaurio/lead-scraper-skill)"
NOMINATIM = "https://nominatim.openstreetmap.org/search"
OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
OVERPASS_TIMEOUT = 60

# Friendly name -> list of OSM key=value selectors (OR-ed together).
CATEGORIES: Dict[str, List[str]] = {
    "dentist": ["amenity=dentist", "healthcare=dentist"],
    "doctor": ["amenity=doctors", "healthcare=doctor"],
    "clinic": ["amenity=clinic", "healthcare=clinic"],
    "physiotherapist": ["healthcare=physiotherapist"],
    "chiropractor": ["healthcare=chiropractor", "healthcare:speciality=chiropractic"],
    "veterinarian": ["amenity=veterinary"],
    "pharmacy": ["amenity=pharmacy"],
    "optician": ["shop=optician", "craft=optician"],
    "lawyer": ["office=lawyer"],
    "accountant": ["office=accountant"],
    "insurance": ["office=insurance"],
    "real estate": ["office=estate_agent"],
    "architect": ["office=architect"],
    "it company": ["office=it"],
    "marketing agency": ["office=advertising_agency", "office=marketing"],
    "consulting": ["office=consulting"],
    "coworking": ["office=coworking", "amenity=coworking_space"],
    "restaurant": ["amenity=restaurant"],
    "cafe": ["amenity=cafe"],
    "coffee shop": ["amenity=cafe", "shop=coffee"],
    "bar": ["amenity=bar", "amenity=pub"],
    "bakery": ["shop=bakery"],
    "hotel": ["tourism=hotel"],
    "hostel": ["tourism=hostel"],
    "gym": ["leisure=fitness_centre", "leisure=sports_centre"],
    "yoga studio": ["leisure=fitness_centre", "sport=yoga"],
    "hair salon": ["shop=hairdresser"],
    "barber": ["shop=hairdresser", "shop=barber"],
    "beauty salon": ["shop=beauty"],
    "spa": ["leisure=spa", "shop=massage"],
    "tattoo": ["shop=tattoo"],
    "car repair": ["shop=car_repair"],
    "car dealer": ["shop=car"],
    "car wash": ["amenity=car_wash"],
    "plumber": ["craft=plumber"],
    "electrician": ["craft=electrician"],
    "hvac": ["craft=hvac"],
    "roofer": ["craft=roofer"],
    "carpenter": ["craft=carpenter"],
    "painter": ["craft=painter"],
    "cleaning": ["shop=dry_cleaning", "shop=laundry", "craft=cleaning"],
    "landscaper": ["craft=gardener", "shop=garden_centre"],
    "florist": ["shop=florist"],
    "pet shop": ["shop=pet"],
    "dog groomer": ["shop=pet_grooming"],
    "photographer": ["craft=photographer", "shop=photo"],
    "printing": ["shop=copyshop", "craft=printer"],
    "bike shop": ["shop=bicycle"],
    "bookstore": ["shop=books"],
    "clothing store": ["shop=clothes"],
    "jewelry": ["shop=jewelry"],
    "furniture": ["shop=furniture"],
    "electronics": ["shop=electronics", "shop=computer"],
    "supermarket": ["shop=supermarket"],
    "school": ["amenity=school"],
    "driving school": ["amenity=driving_school"],
    "language school": ["amenity=language_school"],
    "daycare": ["amenity=childcare", "amenity=kindergarten"],
    "tutoring": ["office=educational_institution", "amenity=prep_school"],
    "church": ["amenity=place_of_worship"],
    "bank": ["amenity=bank"],
    "travel agency": ["shop=travel_agency"],
    "event venue": ["amenity=events_venue"],
    "wedding": ["shop=wedding", "amenity=events_venue"],
    "funeral home": ["shop=funeral_directors"],
    "storage": ["shop=storage_rental"],
    "moving company": ["office=moving_company"],
    "logistics": ["office=logistics"],
    "manufacturer": ["industrial=factory", "man_made=works"],
    "warehouse": ["building=warehouse", "industrial=warehouse"],
    "brewery": ["craft=brewery", "microbrewery=yes"],
    "winery": ["craft=winery"],
    "nonprofit": ["office=association", "office=charity", "office=ngo"],
    "company": ["office=company"],
}


def _curl_json(url: str, data: Optional[bytes], timeout: int) -> dict:
    """Fallback for Pythons linked against old LibreSSL (macOS system python) that
    cannot complete a TLS handshake with some servers. curl ships with macOS/Linux."""
    if not shutil.which("curl"):
        raise RuntimeError("urllib TLS failed and curl is not installed")
    cmd = ["curl", "-sS", "-m", str(timeout), "-A", USER_AGENT, "-H", "Accept: application/json"]
    if data is not None:
        cmd += ["--data-binary", "@-"]
    cmd.append(url)
    proc = subprocess.run(cmd, input=data, capture_output=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"curl failed: {proc.stderr.decode(errors='replace').strip()[:200]}")
    return json.loads(proc.stdout.decode("utf-8"))


def http_get_json(url: str, data: Optional[bytes] = None, retries: int = 3, timeout: int = 120) -> dict:
    last_err: Optional[Exception] = None
    use_curl = False
    for attempt in range(retries):
        try:
            if use_curl:
                return _curl_json(url, data, timeout)
            req = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code in (429, 504, 503):
                time.sleep(5 * (attempt + 1))
                continue
            raise
        except urllib.error.URLError as e:
            last_err = e
            if "SSL" in str(e) or "ssl" in str(e):
                use_curl = True  # retry immediately via curl
                continue
            time.sleep(2 * (attempt + 1))
        except Exception as e:  # noqa: BLE001
            last_err = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"request failed after {retries} attempts: {last_err}")


def geocode(place: str) -> Tuple[str, Optional[int], Tuple[float, float, float, float]]:
    """Returns (display_name, osm_relation_area_id or None, bbox(south, west, north, east))."""
    q = urllib.parse.urlencode({"q": place, "format": "jsonv2", "limit": 1, "polygon_geojson": 0})
    results = http_get_json(f"{NOMINATIM}?{q}")
    if not results:
        raise SystemExit(f"could not geocode '{place}'")
    r = results[0]
    south, north, west, east = (float(x) for x in r["boundingbox"])
    area_id = None
    if r.get("osm_type") == "relation":
        area_id = 3600000000 + int(r["osm_id"])
    elif r.get("osm_type") == "way":
        area_id = 2400000000 + int(r["osm_id"])
    return r.get("display_name", place), area_id, (south, west, north, east)


def build_query(selectors: List[str], area_id: Optional[int], bbox: Tuple[float, float, float, float],
                radius_km: Optional[float], center: Optional[Tuple[float, float]], limit: int) -> str:
    # Bounding box is the default: it is several times faster on the public
    # Overpass servers than an area lookup, and for lead generation the suburbs
    # just outside a city boundary are usually leads too.
    if radius_km and center:
        scope = f"(around:{int(radius_km * 1000)},{center[0]},{center[1]})"
        prefix = ""
    elif area_id:
        scope = "(area.a)"
        prefix = f"area({area_id})->.a;"
    else:
        s, w, n, e = bbox
        scope = f"({s},{w},{n},{e})"
        prefix = ""
    parts = []
    for sel in selectors:
        k, _, v = sel.partition("=")
        tag = f'["{k}"="{v}"]' if v else f'["{k}"]'
        parts.append(f'nwr{tag}["name"]{scope};')
    return f"[out:json][timeout:{OVERPASS_TIMEOUT}];{prefix}({''.join(parts)});out center tags {limit};"


def run_overpass(query: str) -> dict:
    data = urllib.parse.urlencode({"data": query}).encode("utf-8")
    last_err: Optional[Exception] = None
    for endpoint in OVERPASS_ENDPOINTS:
        try:
            return http_get_json(endpoint, data=data, retries=2, timeout=OVERPASS_TIMEOUT + 30)
        except Exception as e:  # noqa: BLE001
            last_err = e
            print(f"overpass endpoint failed ({endpoint}): {e}", file=sys.stderr)
    raise SystemExit(f"all Overpass endpoints failed: {last_err}")


def tag(t: Dict[str, str], *keys: str) -> str:
    for k in keys:
        if t.get(k):
            return t[k].strip()
    return ""


def element_to_row(el: dict, category: str) -> Dict[str, str]:
    t = el.get("tags", {})
    lat = el.get("lat") or el.get("center", {}).get("lat", "")
    lon = el.get("lon") or el.get("center", {}).get("lon", "")
    street = " ".join(x for x in (t.get("addr:housenumber", ""), t.get("addr:street", "")) if x).strip()
    address = ", ".join(x for x in (street, t.get("addr:city", ""), t.get("addr:postcode", "")) if x)
    website = tag(t, "website", "contact:website", "url")
    if website and not website.lower().startswith(("http://", "https://")):
        website = "https://" + website
    return {
        "company_name": t.get("name", ""),
        "category": category,
        "osm_type": t.get("amenity") or t.get("shop") or t.get("office") or t.get("craft")
        or t.get("healthcare") or t.get("leisure") or t.get("tourism") or "",
        "website": website,
        "phone": tag(t, "phone", "contact:phone", "contact:mobile"),
        "email": tag(t, "email", "contact:email"),
        "address": address,
        "city": t.get("addr:city", ""),
        "postcode": t.get("addr:postcode", ""),
        "lat": str(lat),
        "lon": str(lon),
        "opening_hours": t.get("opening_hours", ""),
        "facebook": tag(t, "contact:facebook"),
        "instagram": tag(t, "contact:instagram"),
        "linkedin": tag(t, "contact:linkedin"),
        "osm_id": f"{el.get('type')}/{el.get('id')}",
        "source": "openstreetmap",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--what", help="Business category (see --list-categories), e.g. dentist")
    ap.add_argument("--tag", action="append", default=[], help="Raw OSM selector key=value (repeatable)")
    ap.add_argument("--near", help="Place name to search in, e.g. 'Austin, TX' or 'Berlin'")
    ap.add_argument("--radius-km", type=float, help="Search within a radius (km) of the place centre")
    ap.add_argument("--exact-boundary", action="store_true",
                    help="Restrict to the administrative boundary instead of its bounding box (slower)")
    ap.add_argument("--limit", type=int, default=300, help="Max results (default 300)")
    ap.add_argument("--output", "-o", help="CSV path (default: stdout)")
    ap.add_argument("--with-website-only", action="store_true", help="Drop results that have no website tag")
    ap.add_argument("--list-categories", action="store_true")
    args = ap.parse_args()

    if args.list_categories:
        for name, sels in CATEGORIES.items():
            print(f"{name:20s} {', '.join(sels)}")
        return 0
    if not args.near or not (args.what or args.tag):
        ap.error("--near and one of --what/--tag are required")

    selectors = list(args.tag)
    category = args.what or ", ".join(args.tag)
    if args.what:
        key = args.what.lower().strip()
        if key in CATEGORIES:
            selectors += CATEGORIES[key]
        else:
            # Unknown word: try it as a value across the common business keys.
            v = key.replace(" ", "_")
            selectors += [f"amenity={v}", f"shop={v}", f"office={v}", f"craft={v}", f"healthcare={v}"]
            print(f"'{args.what}' is not a known category; trying generic OSM tags {selectors}. "
                  f"See --list-categories or pass --tag key=value.", file=sys.stderr)

    display, area_id, bbox = geocode(args.near)
    print(f"area: {display}", file=sys.stderr)
    time.sleep(1)  # Nominatim usage policy: max 1 request/second.
    center = ((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2)
    query = build_query(selectors, area_id if args.exact_boundary else None, bbox, args.radius_km, center, args.limit)
    print("querying Overpass (public server, typically 10-60s)...", file=sys.stderr)
    data = run_overpass(query)
    elements = data.get("elements", [])

    rows = [element_to_row(el, category) for el in elements]
    rows = [r for r in rows if r["company_name"]]
    if args.with_website_only:
        rows = [r for r in rows if r["website"]]

    # Dedupe: same website or same name+postcode.
    seen = set()
    unique = []
    for r in rows:
        key = r["website"].lower().rstrip("/") if r["website"] else (r["company_name"].lower(), r["postcode"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(r)
    unique.sort(key=lambda r: (not r["website"], not r["phone"], r["company_name"]))

    cols = list(unique[0].keys()) if unique else list(element_to_row({"tags": {}}, category).keys())
    out = open(args.output, "w", newline="", encoding="utf-8") if args.output else sys.stdout
    try:
        w = csv.DictWriter(out, fieldnames=cols)
        w.writeheader()
        w.writerows(unique)
    finally:
        if args.output:
            out.close()
    with_site = sum(1 for r in unique if r["website"])
    with_phone = sum(1 for r in unique if r["phone"])
    print(f"found {len(unique)} businesses ({with_site} with website, {with_phone} with phone)"
          + (f" -> {args.output}" if args.output else ""), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
