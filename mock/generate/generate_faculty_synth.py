"""Replace real faculty identity (name, email, slug-derived ids) with synthetic names.

Input : mock/lambda/data/faculty.json          (real scraped name/email + synthetic project)
Output: mock/lambda/data/faculty-synth.json    (synthetic name/email; everything else unchanged)

Only identity fields are touched: name, email, slug, url, faculty_id, project_id, and the
"<Lastname> group" phrase generate_faculty_projects.py wrote into project.description.
research_interests, department, title, etc. are left as scraped (not identifying on their own).

Deterministic: each real slug maps to the same synthetic name every run.

Usage:
    python3 -I generate_faculty_synth.py --in ../lambda/data/faculty.json \
        --out ../lambda/data/faculty-synth.json
"""

import argparse
import hashlib
import json
import random
import re
from pathlib import Path

FIRST_NAMES = [
    "Avery", "Blair", "Casey", "Dakota", "Ellis", "Finley", "Greer", "Harlow", "Indigo", "Jules",
    "Kendall", "Lennox", "Marlowe", "Noa", "Oakley", "Paxton", "Quill", "Reese", "Sage", "Tatum",
    "Umber", "Vesper", "Wren", "Xiomara", "Yael", "Zion", "Arden", "Briar", "Cleo", "Dove",
    "Emer", "Fable", "Goldie", "Hollis", "Iris", "Jericho", "Kai", "Lior", "Monroe", "Nico",
]
LAST_NAMES = [
    "Ashworth", "Brennan", "Castellan", "Dunmore", "Ellery", "Faulkner", "Granger", "Halloway",
    "Ivanov", "Jarrett", "Kestrel", "Lindqvist", "Marchetti", "Norwood", "Osei", "Pemberton",
    "Quintrell", "Ravensworth", "Sutcliffe", "Tavares", "Underwood", "Vasko", "Winslow", "Xanthos",
    "Yarrow", "Zelinsky", "Abernathy", "Blackwood", "Carrow", "Delacroix", "Esparza", "Fenwick",
    "Greymont", "Haddon", "Isakov", "Juno", "Kallenberg", "Larchmont", "Moreno", "Nakashima",
]


def rng_for(slug):
    return random.Random(int(hashlib.sha256(("synth-" + slug).encode()).hexdigest()[:12], 16))


def slugify(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def synth_identity(slug, used_slugs):
    rng = rng_for(slug)
    for _ in range(50):
        first, last = rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES)
        new_slug = slugify(f"{first} {last}")
        if new_slug not in used_slugs:
            break
    else:
        new_slug = f"{new_slug}-{len(used_slugs)}"
    used_slugs.add(new_slug)
    name = f"{first} {last}"
    email = f"{first.lower()}.{last.lower()}@mock.example.edu"
    return name, email, new_slug, last


def synthesize(rec, used_slugs):
    old_last = (rec["name"] or "").split()[-1] if rec.get("name") else None
    name, email, slug, last = synth_identity(rec["slug"], used_slugs)

    rec["name"] = name
    rec["email"] = email
    rec["slug"] = slug
    rec["url"] = f"https://ur.arizona.edu/person/{slug}"
    rec["faculty_id"] = slug

    proj = rec.get("project")
    if proj:
        proj["project_id"] = f"proj-{slug}"
        if old_last:
            pattern = re.compile(rf"\b{re.escape(old_last)}\b")
            for field in ("title", "description"):
                if proj.get(field):
                    proj[field] = pattern.sub(last, proj[field])
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    data = json.loads(Path(args.inp).read_text())
    used_slugs = set()
    for rec in data["faculty"]:
        synthesize(rec, used_slugs)

    assert len(used_slugs) == len(data["faculty"]), "duplicate synthetic slugs"

    data["meta"]["note"] = ("Faculty name/email are SYNTHETIC (generated for the mock). "
                             "Department/title/interests/majors/courses are real (scraped). "
                             "`project` is synthetic and flagged inferred.")
    data["meta"]["source"] = "synthesized from https://ur.arizona.edu/find/search-ua-researchers"

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(data, ensure_ascii=False))
    print(json.dumps({"faculty": len(data["faculty"]), "bytes": Path(args.out).stat().st_size}, indent=2))


if __name__ == "__main__":
    main()
