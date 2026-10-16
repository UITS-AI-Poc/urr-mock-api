"""Build mock faculty + project listings from the scraped UR availability snapshot.

Input : s3-data/ur-researchers/researchers.json   (485 real researchers, scrape_ur_researchers.py)
Output: mock/lambda/data/faculty.json

Faculty fields are real (as scraped). Everything under "project" is SYNTHETIC and flagged
`inferred: true`: the source feed has no descriptions, project titles, task lists, application
modes, deadlines or spot counts. Generation is deterministic (seeded per researcher slug), and
uses only the researcher's own scraped interests / majors / prerequisites / department.

Usage:
    python3 -I generate_faculty_projects.py --in ../../s3-data/ur-researchers/researchers.json \
        --out ../lambda/data/faculty.json
"""

import argparse
import hashlib
import json
import random
import re
from datetime import date, timedelta
from pathlib import Path

SNAPSHOT = date(2026, 10, 16)
GENERIC_MAJORS = {"any", "all", "not given", "n/a", "none"}

# Task templates keyed by a coarse field bucket, derived from college/department/interests text.
BUCKETS = [
    ("computing", r"comput|cyber|data|informat|software|machine|statistic|math"),
    ("lab_bio", r"bio|neuro|cell|molecul|physiol|genet|immun|pharm|medic|health|nurs|cancer|ecolog|plant|animal|vet"),
    ("engineering", r"engineer|material|optic|mining|aerospace|chemical|mechanic|electrical|systems"),
    ("physical", r"physic|chem|astro|planet|geo|hydro|atmosph|environment|space"),
    ("social", r"psych|socio|anthro|educ|linguist|communic|politic|econom|history|language|cogni|behavior|public|policy"),
    ("humanities", r"english|philosoph|art|music|theat|film|religio|classic|writing|literat|humanit"),
]
TASKS = {
    "computing": ["Writing and testing code that supports the lab's analysis pipeline",
                  "Cleaning, organizing, and documenting research datasets",
                  "Running experiments and summarizing results for group meetings",
                  "Reading recent papers and helping reproduce published results"],
    "lab_bio": ["Assisting with sample preparation and routine lab procedures",
                "Supporting data collection and keeping careful experiment records",
                "Helping process and organize experimental data",
                "Learning the lab's core techniques alongside graduate students"],
    "engineering": ["Building and testing prototypes or experimental setups",
                    "Collecting measurements and logging test results",
                    "Supporting simulation or modeling runs",
                    "Documenting design decisions and results for the team"],
    "physical": ["Collecting, cataloguing, and processing field or instrument data",
                 "Running analysis scripts and checking outputs for quality",
                 "Helping maintain equipment and sample inventories",
                 "Reading background literature and summarizing it for the group"],
    "social": ["Helping recruit participants and run study sessions",
               "Coding, transcribing, or organizing qualitative and survey data",
               "Assisting with literature reviews and reference management",
               "Supporting basic statistical analysis under a graduate mentor"],
    "humanities": ["Searching archives and sources for relevant material",
                   "Transcribing, annotating, and organizing primary sources",
                   "Assisting with literature reviews and bibliographies",
                   "Helping prepare materials for talks or publications"],
}
INTRO = [
    "The {lab} works on {topics}.",
    "Research in the {lab} centers on {topics}.",
    "The {lab} investigates questions in {topics}.",
]
OPEN_LINE = [
    "Undergraduates join the group as part of an ongoing line of work and are paired with a more experienced member for training.",
    "Students typically start with well-scoped tasks and take on more responsibility as they learn the group's methods.",
    "The group welcomes undergraduates at different stages and works out a role that fits their schedule and background.",
]
DISCLAIMER = ("Illustrative description generated for the mock from this researcher's listed research "
              "areas and department; it is not written by the researcher.")


def rng_for(slug):
    return random.Random(int(hashlib.sha256(slug.encode()).hexdigest()[:12], 16))


def bucket(r):
    blob = " ".join([r.get("primary_department") or "", r.get("college") or "",
                     " ".join(r.get("research_interests") or [])]).lower()
    for name, pat in BUCKETS:
        if re.search(pat, blob):
            return name
    return "social"


def clean_topics(items):
    """Interests are free text split on commas; drop bullet/fragment debris."""
    out = []
    for t in items:
        t = re.sub(r"^[\s\-\u2022*\d.)]+", "", t).strip()
        t = re.sub(r"^(and|or)\s+", "", t, flags=re.I).strip(" .;:")
        if 2 < len(t) <= 50 and len(t.split()) <= 6 and t.lower() not in {x.lower() for x in out}:
            out.append(t)
    return out


def topics_for(r):
    raw = r.get("research_interests_raw")
    parts = re.split(r"(?:^|\s)-\s*(?=[A-Za-z])|[;,\n\u2022]", raw) if raw else (r.get("research_interests") or [])
    ints = clean_topics(parts)
    if ints:
        return ints[:4], "interests"
    dept = r.get("primary_department")
    majors = [m for m in (r.get("majors_considered") or []) if m.lower() not in GENERIC_MAJORS]
    if dept:
        return [dept], "department"
    return [], "none"


def oxford(items):
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + (", and " if len(items) > 2 else " and ") + items[-1]


def lab_name(r):
    last = (r["name"] or "").split()[-1] if r.get("name") else "research"
    return f"{last} group" if r.get("name") else "research group"


def timing(rng, r):
    """application_mode + status + dates, relative to the snapshot date."""
    mode = rng.choices(["conversational", "structured"], weights=[.7, .3])[0]
    if mode == "conversational":
        status = rng.choices(["open", "rolling"], weights=[.35, .65])[0]
        return mode, status, None, None, None
    status = rng.choices(["open", "not_yet_open", "closed"], weights=[.6, .2, .2])[0]
    if status == "open":
        opens, closes = SNAPSHOT - timedelta(days=rng.randint(5, 40)), SNAPSHOT + timedelta(days=rng.randint(3, 60))
    elif status == "not_yet_open":
        opens = SNAPSHOT + timedelta(days=rng.randint(10, 60))
        closes = opens + timedelta(days=rng.randint(21, 45))
    else:
        closes = SNAPSHOT - timedelta(days=rng.randint(3, 60))
        opens = closes - timedelta(days=rng.randint(21, 45))
    return mode, status, opens.isoformat(), closes.isoformat(), rng.randint(1, 4)


def build(r):
    rng = rng_for(r["slug"])
    topics, topic_src = topics_for(r)
    b = bucket(r)
    lab = lab_name(r)
    if topics:
        title = f"Research in {oxford(topics[:2])}"
        para1 = rng.choice(INTRO).format(lab=lab, topics=oxford(topics))
    else:
        title = "Undergraduate research opportunity"
        para1 = f"The {lab} offers undergraduate research opportunities."
    description = f"{para1} {rng.choice(OPEN_LINE)}"
    mode, status, opens, closes, spots = timing(rng, r)
    types = [t for t in r.get("opportunity_types") or [] if t != "Not given"]
    return {
        "project_id": f"proj-{r['slug']}",
        "title": title,
        "description": description,
        "likely_tasks": rng.sample(TASKS[b], 3),
        "tasks_note": "Inferred for the mock from the researcher's listed areas; not itemized by the researcher.",
        "application_mode": mode,
        "application_status": status,
        "application_opens": opens,
        "application_closes": closes,
        "spots": spots,
        "incentive": "Paid" if "Paid" in types else ("None (volunteer)" if "Volunteer" in types else None),
        "credit": "UA credit available" if "For credit" in types else None,
        "format": "In-person",
        "inferred": True,
        "inferred_from": topic_src,
        "disclaimer": DISCLAIMER,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    researchers = json.load(open(args.inp))

    faculty = []
    for r in researchers:
        rec = dict(r)
        rec["faculty_id"] = r["slug"]
        rec["project"] = build(r) if r["offering_opportunities"] else None
        faculty.append(rec)

    out = {
        "meta": {
            "source": "https://ur.arizona.edu/find/search-ua-researchers",
            "snapshot_date": "2026-10-16", "snapshot_count": len(faculty),
            "note": "Faculty fields are real (scraped). `project` is synthetic and flagged inferred.",
        },
        "faculty": faculty,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False))
    ps = [f["project"] for f in faculty if f["project"]]
    from collections import Counter
    print(json.dumps({
        "faculty": len(faculty), "projects": len(ps),
        "modes": dict(Counter(p["application_mode"] for p in ps)),
        "status": dict(Counter(p["application_status"] for p in ps)),
        "title_source": dict(Counter(p["inferred_from"] for p in ps)),
        "bytes": Path(args.out).stat().st_size,
    }, indent=2))


if __name__ == "__main__":
    main()
