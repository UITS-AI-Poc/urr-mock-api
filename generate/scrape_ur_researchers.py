"""ONE-OFF: snapshot the UA undergraduate-research availability listing into flat files.

Source: https://ur.arizona.edu/find/search-ua-researchers  (public; /find/ is not disallowed
by robots.txt) plus each researcher's public /person/<slug> page.

Politeness: identifiable User-Agent, 1 request/second, responses cached on disk so a re-run
(or interruption) does not refetch. Run once; commit the output, do not run in CI.

Usage:
    python3 -I scrape_ur_researchers.py --out ../../s3-data/ur-researchers [--limit N]

Writes: researchers.json, researchers.csv, scrape_report.json   (cache in <out>/.cache/)
"""

import argparse
import csv
import hashlib
import html
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

BASE = "https://ur.arizona.edu"
LIST_URL = BASE + "/find/search-ua-researchers?page={page}"
UA = "Mozilla/5.0 (compatible; ua-urr-mock-snapshot; one-off; contact: bbendick@gmail.com)"
DELAY = 1.0

FIELDS = {  # drupal field class suffix -> output key
    "research-interest": "research_interests",
    "opportunity": "offering_opportunities",
    "prerequisite-courses": "prerequisite_courses",
    "majors": "majors_considered",
    "types": "opportunity_types",
    "description": "description",
    "research-start-date": "start_date",
    "research-end-date": "end_date",
    "imported-college": "college",
    "primary-department": "primary_department",
    "affiliated-departments": "affiliated_departments",
    "research-location": "research_locations",
    "website": "website",
}
LIST_KEYS = {"research_interests", "majors_considered", "opportunity_types",
             "affiliated_departments", "research_locations"}


def fetch(url, cache_dir):
    f = cache_dir / (hashlib.sha1(url.encode()).hexdigest() + ".html")
    if f.exists():
        return f.read_text()
    for attempt in range(3):
        try:
            time.sleep(DELAY)
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                body = r.read().decode("utf-8", "replace")
            f.write_text(body)
            return body
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return ""
            if attempt == 2:
                raise
            time.sleep(5 * (attempt + 1))
        except urllib.error.URLError:
            if attempt == 2:
                raise
            time.sleep(5 * (attempt + 1))


def text(fragment):
    fragment = re.sub(r"<(script|style).*?</\1>", "", fragment, flags=re.S)
    fragment = re.sub(r"<(br|/p|/li|/div|/h\d)[^>]*>", "\n", fragment)
    s = html.unescape(re.sub(r"<[^>]+>", "", fragment)).replace("\xa0", " ")
    s = re.sub(r"[ \t]+", " ", s)
    return re.sub(r"\n\s*\n+", "\n", s).strip()


def list_page(body):
    """Rows from the results table: slug + the columns shown in the list."""
    rows = []
    for tr in re.findall(r"<tr>(.*?)</tr>", body, re.S):
        m = re.search(r'href="(/person/[^"#?]+)"', tr)
        if m:
            rows.append(m.group(1))
    return rows


def field_values(main, suffix):
    """Value text of a drupal field, with its label removed. Returns None if absent."""
    m = re.search(r'<div class="field field--name-field-ur-%s[ "].*?(?=<div class="field field--name-|</article|\Z)'
                  % re.escape(suffix), main, re.S)
    if not m:
        return None
    block = m.group(0)
    block = re.sub(r'<div class="field__label[^"]*">.*?</div>', "", block, count=1, flags=re.S)
    items = re.findall(r'<div class="field__item[^"]*">(.*?)</div>', block, re.S)
    vals = [text(i) for i in items] if items else [text(block)]
    return [v for v in vals if v]


def parse_person(slug, body):
    main = (re.search(r"<main.*?</main>", body, re.S) or re.search(r".*", body, re.S)).group(0)
    h1 = re.search(r"<h1[^>]*>(.*?)</h1>", main, re.S)
    name = text(h1.group(1)) if h1 else None
    rec = {"slug": slug.rsplit("/", 1)[-1], "url": BASE + slug, "name": name}

    # Header block under the name: title line, graduate-faculty line, office, email.
    head = text(main[h1.end(): h1.end() + 1500]) if h1 else ""
    lines = [l for l in head.split("\n") if l.strip()]
    rec["title"] = lines[0] if lines and "@" not in lines[0] else None
    em = re.search(r"[\w.+-]+@[\w.-]+\.\w+", main)
    rec["email"] = em.group(0) if em else None
    rec["graduate_faculty"] = "Member of the Graduate Faculty" in head

    for suffix, key in FIELDS.items():
        vals = field_values(main, suffix)
        if vals is None:
            rec[key] = [] if key in LIST_KEYS else None
        elif key in LIST_KEYS:
            flat = []
            for v in vals:
                flat += [p.strip() for p in re.split(r",|\n", v) if p.strip()]
            rec[key] = flat
        else:
            rec[key] = " ".join(vals)

    raw = field_values(main, "research-interest")
    rec["research_interests_raw"] = " ".join(raw) if raw else None
    rec["offering_opportunities"] = (rec["offering_opportunities"] or "").strip().lower() == "yes"
    for k in ("description",):
        if rec[k] and rec[k].lower() == "no description given":
            rec[k] = None
    site = re.search(r'href="(https?://[^"]+)"[^>]*>[^<]*(?:lab|website|site)', main, re.I)
    rec["lab_website"] = rec.pop("website") or (site.group(1) if site else None)
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int, default=0, help="stop after N researchers (testing)")
    args = ap.parse_args()
    out = Path(args.out)
    cache = out / ".cache"
    cache.mkdir(parents=True, exist_ok=True)

    slugs, page = [], 0
    while True:
        rows = list_page(fetch(LIST_URL.format(page=page), cache))
        if not rows:
            break
        slugs += [s for s in rows if s not in slugs]
        print(f"list page {page}: {len(rows)} rows, {len(slugs)} unique", file=sys.stderr)
        page += 1
        if page > 200:
            sys.exit("pagination did not terminate")
    if args.limit:
        slugs = slugs[: args.limit]

    records, failed = [], []
    for i, s in enumerate(slugs, 1):
        body = fetch(BASE + s, cache)
        if not body:
            failed.append(s)
            continue
        records.append(parse_person(s, body))
        if i % 25 == 0:
            print(f"person {i}/{len(slugs)}", file=sys.stderr)

    (out / "researchers.json").write_text(json.dumps(records, indent=1, ensure_ascii=False))
    cols = list(records[0])
    with open(out / "researchers.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in records:
            w.writerow([";".join(v) if isinstance(v, list) else v for v in (r[c] for c in cols)])

    report = {
        "snapshot_date": date.today().isoformat(), "source": BASE + "/find/search-ua-researchers",
        "list_pages": page, "researchers": len(records), "failed": failed,
        "offering_yes": sum(r["offering_opportunities"] for r in records),
        "missing": {c: sum(1 for r in records if not r[c]) for c in cols},
    }
    (out / "scrape_report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
