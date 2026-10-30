"""Build the mock NSIF dataset from the raw files in s3-data.

Reads raw files locally and writes ONLY derived, non-identifying data:
  - real course codes, department ids/names, program records (no PII)
  - fully synthetic students (invented ids, names, netIDs)
  - enrollments drawn from aggregate (k >= MIN_K) plan->subject weights,
    never from an individual real student's course list

Usage:
    python3 -I generate_dataset.py --s3-data ../../s3-data --out ../lambda/data/dataset.json
"""

import argparse
import csv
import html
import json
import math
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

SEED = 20261016
MIN_K = 50  # minimum real students behind any plan->subject aggregate
N_STUDENTS = 150
N_PROGRAMS = 60

# ---------------------------------------------------------------------------
# Config mirrored from services/nsif/config.py (UA-AI2S/undergraduate-research-recommender)
# ---------------------------------------------------------------------------
CAREER_TO_DOMAINS = {
    "career_health": ["healthcare_medicine"],
    "career_engineering": ["engineering"],
    "career_data": ["data_science_statistics"],
    "career_arts": ["arts_humanities"],
    "career_business": ["business_economics"],
    "career_educ": ["education_pedagogy"],
    "career_enviro": ["environment_sustainability"],
    "career_global": ["social_behavioral_sciences"],
    "career_law": ["law_policy"],
    "career_research": [],
}
CAREER_COLUMNS = [
    "career_unsure", "career_arts", "career_business", "career_data", "career_educ",
    "career_engineering", "career_enviro", "career_global", "career_health",
    "career_law", "career_research", "career_notlisted",
]
EXP_COLUMNS = [
    "exp_internship", "exp_networking", "exp_precept", "exp_facresearch",
    "exp_empresearch", "exp_teaching", "exp_studyabroad", "exp_sigproject",
    "exp_leadership", "exp_skills", "exp_service", "exp_other", "exp_none",
]
F21_EXTRA_EXP = ["exp_employment", "exp_coop"]
# Verified against an NSIF spreadsheet header row (supplied by the user, 2026-10-16). Columns
# vary by term in the real data; this is the set seen in that header (inv_othertext is separate).
INV_COLUMNS = [
    "inv_acadclubs", "inv_employment", "inv_fsp", "inv_health", "inv_leadership",
    "inv_culturalresource", "inv_internship", "inv_recsports", "inv_reslife", "inv_studentgov",
    "inv_sustainability", "inv_peermentor", "inv_firstgen", "inv_arts", "inv_relig", "inv_other",
]

# NSIF terms present in the repo's TERM_DEMOGRAPHIC_MAP, in chronological order.
TERMS = ["F21", "S22", "F22", "S23", "F23", "S24", "F24", "S25", "F25"]
STRM_BY_TERM = {"F21": "2214", "S22": "2221", "F22": "2224", "S23": "2231", "F23": "2234",
                "S24": "2241", "F24": "2244", "S25": "2251", "F25": "2254"}
TERM_BY_STRM = {v: k for k, v in STRM_BY_TERM.items()}


def term_parts(term):
    season = "Fall" if term[0] == "F" else "Spring"
    return 2000 + int(term[1:]), season


# subject -> real department id (from staff-titles-enriched.json). None = no owning dept.
SUBJECT_DEPT = {
    "MATH": "0430", "CHEM": "2536", "ENGL": "0429", "PSY": "0423", "SPAN": "0441",
    "PSIO": "0705", "PHYS": "0411", "MIS": "3010", "NURS": "3301", "NSC": "2529",
    "ECOL": "0420", "MCB": "0417", "ECON": "3009", "ACCT": "3007", "LAW": "3603",
    "CLAS": "0405", "PHIL": "0428", "CSC": "0412", "BNAD": "3016", "BNAN": "3019",
    "MGMT": "3004", "FIN": "3003", "MKTG": "3006", "POL": "0465", "ART": "3504",
    "MUS": "3503", "DNC": "3508", "FTV": "3509", "ANTH": "0410", "COMM": "3505",
    "RELI": "0405", "HIST": "0415", "AFAS": "0435", "SOC": "0418", "GEOG": "3008",
    "ISTA": "0481", "FREN": "0440", "ASTR": "0422", "SLHS": "3502", "LING": "0431",
    "EAS": "0439", "AME": "2305", "MSE": "2804", "CHEE": "2803", "HNRS": "2514", "TLS": "3222",
    "EDP": "3211", "SERP": "3204", "JPN": "0439", "UNIV": None,
}

# Program (college) code -> career flag probabilities (synthetic, hand-set).
COLLEGE_CAREER = {
    "USCNC": {"career_health": .35, "career_research": .45, "career_data": .25, "career_enviro": .15, "career_engineering": .10},
    "USBSC": {"career_law": .20, "career_global": .25, "career_research": .30, "career_educ": .10, "career_health": .15, "career_business": .10},
    "UBUSN": {"career_business": .80, "career_data": .20, "career_law": .10, "career_global": .15},
    "UENGR": {"career_engineering": .80, "career_data": .35, "career_research": .25, "career_enviro": .15, "career_business": .10},
    "UAGSC": {"career_enviro": .35, "career_health": .30, "career_business": .15, "career_research": .30},
    "UMDTC": {"career_health": .80, "career_research": .35},
    "UNURS": {"career_health": .90},
    "UHMNT": {"career_arts": .30, "career_educ": .20, "career_law": .15, "career_global": .20, "career_research": .20},
    "UFNRT": {"career_arts": .80, "career_educ": .15, "career_business": .10},
    "UEDUC": {"career_educ": .90},
    "UISCL": {"career_data": .45, "career_engineering": .20, "career_business": .20, "career_research": .25},
    "UARCH": {"career_arts": .25, "career_enviro": .30, "career_engineering": .25, "career_business": .10},
    "UPBLH": {"career_health": .80, "career_research": .35, "career_global": .20},
    "UPHRM": {"career_health": .80, "career_research": .40},
    "UHNRS": {"career_research": .50},
}
EXP_PROB = {
    "exp_internship": .55, "exp_networking": .35, "exp_precept": .10, "exp_facresearch": .30,
    "exp_empresearch": .12, "exp_teaching": .10, "exp_studyabroad": .25, "exp_sigproject": .20,
    "exp_leadership": .30, "exp_skills": .30, "exp_service": .30, "exp_other": .04, "exp_none": .04,
}
INV_PROB = {
    "inv_acadclubs": .40, "inv_employment": .25, "inv_fsp": .08, "inv_health": .20,
    "inv_leadership": .30, "inv_culturalresource": .12, "inv_internship": .30, "inv_recsports": .30,
    "inv_reslife": .20, "inv_studentgov": .06, "inv_sustainability": .10, "inv_peermentor": .12,
    "inv_firstgen": .12, "inv_arts": .15, "inv_relig": .08, "inv_other": .04,
}
OTHER_TEXT = ["Journalism", "Sports medicine", "Public service", "Entrepreneurship",
              "Not sure yet", "Film production", "Archaeology", "Urban planning"]
FIRST = ("Aiden Alicia Amara Andre Aria Beatriz Bianca Caleb Camila Carlos Chloe Dalia Dmitri Elena Elijah "
         "Emma Farah Gabriel Hana Hector Imani Isabella Jamal Jasmine Javier Kai Keiko Leila Liam Lucia "
         "Malik Maya Mateo Mei Mohammed Nadia Naomi Nico Noah Olivia Priya Rafael Rosa Samir Sofia Talia "
         "Tariq Valeria Wyatt Xavier Yara Zoe Zane Imogen Joaquin Kalani Lena Marcus Nia Owen Paloma").split()
LAST = ("Alvarez Anderson Bennett Castillo Chen Cooper Delgado Diaz Edwards Fischer Flores Garcia Gupta "
        "Hamilton Harper Hernandez Huang Ibrahim Jackson Kim Kowalski Lee Lopez Martinez Mendoza Morales "
        "Nguyen Okafor Ortiz Patel Perez Quinn Ramirez Reyes Rivera Robinson Salazar Sanchez Shah Silva "
        "Singh Tran Turner Vasquez Walker Watson Whitaker Yazzie Young Zhang Begay Tsosie Nez Holiday "
        "Brooks Foster Grant Hayes Ito Jain Khan Lam Moreno Nakamura").split()


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------
def load_plans(path):
    """UGRD plan code -> (plan descr, college program code, college descr, plan type)."""
    plans = {}
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))[1:]
    for r in rows:
        if r[0] == "UGRD":
            plans[r[4]] = (r[6], r[2], r[3], r[5])
    return plans


def load_active_ugrd(path):
    """emplid -> plan for active undergrads. Held in memory only; never written out."""
    out = {}
    with open(path, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if r["SCTCareer"] == "UGRD":
                out[r["emplid"]] = r["Plan"]
    return out


def load_departments(path):
    d = json.load(open(path))
    depts = {}
    for x in d:
        depts[x["employeePrimaryDept"][0]] = x["deptName"]
    real_staff_ids = {e for x in d for e in x.get("emplId", [])}
    real_staff_uids = {u for x in d for u in x.get("uid", [])}
    return depts, real_staff_ids, real_staff_uids


def scan_classlist(path, emplid_plan, subjects):
    """One pass over the classlist. Returns aggregates only, plus the set of real emplids
    (kept for the PII check, never written out)."""
    plan_students = defaultdict(set)
    plan_subj = defaultdict(Counter)
    global_subj = Counter()
    course_total = Counter()
    course_terms = defaultdict(Counter)
    real_ids = set()
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            e, subj = r["EMPLID"], r["SUBJECT"]
            real_ids.add(e)
            plan = emplid_plan.get(e)
            if plan and subj in subjects:
                plan_students[plan].add(e)
                plan_subj[plan][subj] += 1
                global_subj[subj] += 1
            term = TERM_BY_STRM.get(r["STRM"])
            if term and subj in subjects:
                code = (subj, r["CATALOG_NBR"].strip())
                course_total[code] += 1
                course_terms[code][term] += 1
    return plan_students, plan_subj, global_subj, course_total, course_terms, real_ids


def clean_html(s):
    s = re.sub(r"<(br|/p|/li)\s*/?>", "\n", s or "", flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s).replace("\xa0", " ")
    return re.sub(r"\n{3,}", "\n\n", s).strip()


def iso_date(s):
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", (s or "").strip())
    return f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}" if m else None


def load_programs(path, rng):
    rows = list(csv.DictReader(open(path, encoding="utf-8-sig", newline="")))
    p = "Account_Name__r."
    typed = [r for r in rows if r[p + "Program_Type__c"] or r[p + "Topic__c"]]
    latest = {}  # dedupe by display name, keep the latest end date
    for r in typed:
        name = r[p + "Display_Name_Formula__c"].strip()
        key = iso_date(r["End_Date__c"]) or ""
        if name and (name not in latest or key >= (iso_date(latest[name]["End_Date__c"]) or "")):
            latest[name] = r
    research = [r for r in latest.values() if r[p + "Program_Type__c"] == "Research"]
    rest = [r for r in latest.values() if r[p + "Program_Type__c"] != "Research"]
    rng.shuffle(rest)
    chosen = research[:N_PROGRAMS] + rest[: max(0, N_PROGRAMS - len(research))]
    out = []
    for r in sorted(chosen, key=lambda r: r[p + "Display_Name_Formula__c"]):
        form = r["Application_Form_URL__c"]
        m = re.search(r'href="([^"]+)"', form)
        out.append({
            "id": r["Id"],
            "name": r[p + "Display_Name_Formula__c"].strip(),
            "org_id": r[p + "Parent.Official_Org__c"] or None,
            "description": clean_html(r[p + "Program_Description__c"])[:2000] or None,
            "website": r[p + "Program_Website__c"] or None,
            "length": r[p + "Length_of_Program__c"] or None,
            "incentive": {"Yes": True, "No": False}.get(r[p + "Incentive__c"]),
            "topic": r[p + "Topic__c"] or None,
            "mentoring_information": clean_html(r[p + "Mentoring_Information__c"])[:1000] or None,
            "location": r[p + "Location__c"] or None,
            "eligibility": clean_html(r[p + "Eligibility__c"])[:1000] or None,
            "program_type": r[p + "Program_Type__c"] or None,
            "credit_types": [x for x in r[p + "Credit_Type__c"].split(";") if x],
            "format": r[p + "Program_Format__c"] or None,
            "audiences": [x for x in r[p + "Audiences__c"].split(";") if x],
            "start_date": iso_date(r["Start_Date__c"]),
            "end_date": iso_date(r["End_Date__c"]),
            "application_active": {"TRUE": True, "FALSE": False}.get(r["Application_Active__c"]),
            "application_open": iso_date(r["Application_Open__c"]),
            "application_closed": iso_date(r["Application_Closed__c"]),
            "application_url": m.group(1) if m else (form or None),
        })
    return out


# ---------------------------------------------------------------------------
# Synthetic students
# ---------------------------------------------------------------------------
def wchoice(rng, weighted):
    items, weights = zip(*weighted)
    return rng.choices(items, weights=weights, k=1)[0]


def build_students(rng, plan_pool, plan_info, plan_subj_w, plan_main_subj, catalog, depts,
                   real_ids, real_netids):
    by_subject = defaultdict(list)
    for c in catalog:
        by_subject[c["subject"]].append(c)

    used_ids, used_nets = set(), set()
    students, enrollments = [], {}
    n_missing_first = n_missing_college = n_missing_net = 0

    for i in range(N_STUDENTS):
        sid = None
        while sid is None or sid in used_ids or sid in real_ids:
            sid = "9" + "".join(rng.choice("0123456789") for _ in range(7))
        used_ids.add(sid)
        first, last = rng.choice(FIRST), rng.choice(LAST)
        net = None
        while net is None or net in used_nets or net in real_netids:
            net = f"{first[0]}{last}{rng.randint(1, 99)}".lower()
        used_nets.add(net)

        plan_code = wchoice(rng, plan_pool)
        plan_name, prog_code, college, _ = plan_info[plan_code]
        subj = plan_main_subj.get(plan_code)
        dept_id = SUBJECT_DEPT.get(subj) if subj else None
        dept_name = depts.get(dept_id) if dept_id else None

        # Which NSIF terms this student filled the survey in.
        t0 = rng.randrange(0, len(TERMS) - 1)
        n_rec = rng.choices([1, 2, 3], weights=[.65, .25, .10])[0]
        idxs = sorted({t0} | {min(len(TERMS) - 1, t0 + k) for k in range(1, n_rec)})
        probs = COLLEGE_CAREER.get(prog_code, {})
        base_career = {k: v for k, v in probs.items()}

        records = []
        for ti in idxs:
            term = TERMS[ti]
            year, season = term_parts(term)
            career = [c for c in CAREER_COLUMNS if rng.random() < base_career.get(c, .04)
                      and c not in ("career_unsure", "career_notlisted")]
            if not career and rng.random() < .35:
                career = ["career_unsure"]
            if rng.random() < .05:
                career.append("career_notlisted")
            exp = [c for c in EXP_COLUMNS if rng.random() < EXP_PROB[c]]
            if "career_research" in career and rng.random() < .5 and "exp_facresearch" not in exp:
                exp.append("exp_facresearch")
            if "exp_none" in exp and len(exp) > 1:
                exp = [e for e in exp if e != "exp_none"]
            if term == "F21":
                exp += [c for c in F21_EXTRA_EXP if rng.random() < .2]
            inv = [c for c in INV_COLUMNS if rng.random() < INV_PROB[c]]
            if not (career or exp or inv):  # real ingest drops non-respondents
                career = ["career_unsure"]
            domains = []
            for c in career:
                for d in CAREER_TO_DOMAINS.get(c, []):
                    if d not in domains:
                        domains.append(d)
            records.append({
                "student_id": sid, "term": term, "term_year": year, "term_season": season,
                "full_name": f"{first} {last}", "first_name": first, "last_name": last,
                "email": f"{net}@mock.invalid", "net_id": net,
                "college": college, "department": dept_name, "plan": plan_name,
                "sub_plan": None, "campus": rng.choices(["Tucson", "Online"], weights=[.93, .07])[0],
                "career_interests": career, "experience_preferences": exp,
                "involvement_interests": inv,
                "career_othertext": rng.choice(OTHER_TEXT) if "career_notlisted" in career else None,
                "exp_othertext": rng.choice(OTHER_TEXT) if "exp_other" in exp else None,
                "inv_othertext": rng.choice(OTHER_TEXT) if "inv_other" in inv else None,
                "research_domains": domains,
            })

        # Edge cases for frontend robustness (deterministic positions).
        if i == 7:
            for r in records: r["first_name"] = None; n_missing_first += 1
        if i == 23:
            for r in records: r["college"] = None; r["department"] = None; n_missing_college += 1
        if i == 41:
            for r in records: r["net_id"] = None; r["email"] = None; n_missing_net += 1
        students.extend(records)

        # Enrollments: up to 4 academic terms from the first survey term, drawn from aggregate weights.
        weights = plan_subj_w[plan_code]
        taken, per_term = set(), []
        for k, ti in enumerate(range(t0, min(len(TERMS), t0 + 4))):
            term = TERMS[ti]
            pref_level = min(4, 1 + k // 2) * 100
            courses = []
            for _ in range(rng.choice([4, 5, 5])):
                s = wchoice(rng, weights)
                pool = [c for c in by_subject[s] if term in c["terms"] and c["code"] not in taken] \
                    or [c for c in by_subject[s] if c["code"] not in taken]
                if not pool:
                    continue
                c = rng.choices(pool, weights=[
                    math.sqrt(c["enrollment_total"]) * math.exp(-abs(c["level"] - pref_level) / 150)
                    for c in pool])[0]
                taken.add(c["code"])
                courses.append(c["code"])
            per_term.append({"term": term, "courses": courses})
        enrollments[sid] = per_term
    return students, enrollments


# ---------------------------------------------------------------------------
# Demo personas for the frontend's student selector (fixed, hand-set, synthetic).
# class_standing is NOT part of the NSIF record (it comes from UAccess in the prototype), so it
# lives in dataset["personas"], separate from the NSIF-shaped student records.
# ---------------------------------------------------------------------------
PERSONAS = [  # the students in the prototype's "Viewing as" dropdown (the faculty entry is not a student)
    dict(pid="jordan", sid="90000001", net="jordan.demo", first="Jordan", last="Alvarez",
         label="Jordan Alvarez \u2014 Sophomore, Psychology & Neuroscience", major_display="Psychology & Neuroscience",
         blurb="Sophomore \u00b7 Psychology & Neuroscience \u2014 knows what they want",
         prefs={"volunteer": True, "for_credit": True},
         plan="Neuroscience & Cognitive Sci", college="College of Science", dept="0423", standing="Sophomore",
         career=["career_health", "career_research"],
         exp=["exp_facresearch", "exp_skills", "exp_service"], inv=["inv_acadclubs", "inv_health"],
         courses=[["PSY 101", "NSC 101", "MATH 112"], ["PSY 230", "PSY 200", "NSC 170C1"]]),
    dict(pid="amara", sid="90000002", net="amara.demo", first="Amara", last="Johnson",
         label="Amara Johnson \u2014 Freshman, Physiology", major_display="Physiology",
         blurb="Freshman \u00b7 Physiology \u2014 just exploring, no research experience yet",
         prefs={"for_credit": True},
         plan="Physiology", college="College of Medicine", dept="0705", standing="Freshman",
         career=["career_unsure", "career_health"],
         exp=["exp_service", "exp_facresearch"], inv=["inv_health", "inv_firstgen"],
         courses=[["PSIO 101", "CHEM 151", "MATH 112"]]),
    dict(pid="diego", sid="90000003", net="diego.demo", first="Diego", last="Ramirez",
         label="Diego Ramirez \u2014 Junior, Mechanical Engineering", major_display="Mechanical Engineering",
         blurb="Junior \u00b7 Mechanical Engineering \u2014 needs paid work, cares about sustainability",
         prefs={"paid": True},
         plan="Mechanical Engineering", college="College of Engineering", dept="2305", standing="Junior",
         career=["career_engineering", "career_enviro"],
         exp=["exp_internship", "exp_skills", "exp_sigproject"], inv=["inv_employment", "inv_sustainability"],
         courses=[["MATH 129", "PHYS 141", "CHEM 151"], ["MATH 254", "PHYS 241", "AME 209"]]),
    dict(pid="mei", sid="90000004", net="mei.demo", first="Mei", last="Tanaka",
         label="Mei Tanaka \u2014 Freshman, Computer Science", major_display="Computer Science",
         blurb="Freshman \u00b7 Computer Science \u2014 data-curious, would take pay or credit",
         prefs={"paid": True, "for_credit": True},
         plan="Computer Science", college="College of Science", dept="0412", standing="Freshman",
         career=["career_data", "career_unsure"],
         exp=["exp_internship", "exp_skills"], inv=["inv_acadclubs"],
         courses=[["CSC 110", "MATH 122A", "ENGL 101"]]),
]
PERSONA_TERM = "F25"


def add_personas(students, enrollments, catalog_codes, depts):
    """Append persona NSIF records (F25) and enrollments; return the persona list."""
    year, season = term_parts(PERSONA_TERM)
    out = []
    for p in PERSONAS:
        domains = []
        for c in p["career"]:
            for d in CAREER_TO_DOMAINS.get(c, []):
                if d not in domains:
                    domains.append(d)
        students.append({
            "student_id": p["sid"], "term": PERSONA_TERM, "term_year": year, "term_season": season,
            "full_name": f"{p['first']} {p['last']}", "first_name": p["first"], "last_name": p["last"],
            "email": f"{p['net']}@mock.invalid", "net_id": p["net"],
            "college": p["college"], "department": depts.get(p["dept"]), "plan": p["plan"],
            "sub_plan": None, "campus": "Tucson",
            "career_interests": p["career"], "experience_preferences": p["exp"],
            "involvement_interests": p["inv"], "career_othertext": None, "exp_othertext": None,
            "inv_othertext": None, "research_domains": domains,
        })
        terms = ["F24", "S25"] if len(p["courses"]) == 2 else ["F25"]
        enrollments[p["sid"]] = [
            {"term": t, "courses": [c for c in cs if c in catalog_codes]}
            for t, cs in zip(terms, p["courses"])
        ]
        out.append({"student_id": p["sid"], "net_id": p["net"], "persona_id": p["pid"], "label": p["label"],
                    "class_standing": p["standing"], "major": p["major_display"], "blurb": p["blurb"],
                    "preferences": p["prefs"]})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--s3-data", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    src, out = Path(args.s3_data), Path(args.out)
    rng = random.Random(SEED)

    plans = load_plans(src / "UA_SR_CAREER_PROG_PLAN.csv")
    emplid_plan = load_active_ugrd(src / "urr_active_students.csv")
    depts, real_staff_ids, real_staff_uids = load_departments(src / "staff-titles-enriched.json")
    missing = {d for d in SUBJECT_DEPT.values() if d and d not in depts}
    if missing:
        sys.exit(f"SUBJECT_DEPT references unknown department ids: {sorted(missing)}")

    print("scanning classlist (1.5M rows)...")
    plan_students, plan_subj, global_subj, course_total, course_terms, class_ids = scan_classlist(
        src / "classlist_urr_dec_19.csv", emplid_plan, set(SUBJECT_DEPT))

    # Real identifiers, held in memory only for the PII check.
    en = json.load(open(src / "emplid-netid.json"))
    real_ids = class_ids | set(emplid_plan) | real_staff_ids | {x["emplid"] for x in en}
    real_netids = {x["netid"] for x in en} | real_staff_uids

    # Course catalog (real codes, no titles available in the source).
    catalog = []
    for (subj, cat), total in course_total.items():
        m = re.match(r"\d+", cat)
        if total < 100 or not m:
            continue
        catalog.append({
            "code": f"{subj} {cat}", "subject": subj, "catalog_nbr": cat,
            "level": int(m.group()) // 100 * 100, "department_id": SUBJECT_DEPT[subj],
            "enrollment_total": total,
            "terms": [t for t in TERMS if course_terms[(subj, cat)][t] >= 10],
        })
    catalog.sort(key=lambda c: (c["subject"], c["catalog_nbr"]))

    # Plan pool: undergrad majors with a real college and enough active students.
    plan_counts = Counter(emplid_plan.values())
    pool, plan_info = [], {}
    prog_subj = defaultdict(Counter)
    prog_n = Counter()
    for p, n in plan_counts.items():
        if p in plans:
            prog_subj[plans[p][1]].update(plan_subj[p])
            prog_n[plans[p][1]] += len(plan_students[p])
    excluded = {"UCERT", "UNDG", "UCLAS", "UTCH"}
    plan_subj_w, plan_main_subj = {}, {}
    gtotal = sum(global_subj.values())
    for p, n in plan_counts.items():
        info = plans.get(p)
        if not info or info[3] not in ("Major", "Major (Secondary)") or info[1] in excluded or n < 30:
            continue
        k = len(plan_students[p])
        if k >= MIN_K:
            counter, ptotal = plan_subj[p], sum(plan_subj[p].values())
        elif prog_n[info[1]] >= MIN_K:
            counter, ptotal = prog_subj[info[1]], sum(prog_subj[info[1]].values())
        else:
            continue
        pool.append((p, n))
        plan_info[p] = info
        plan_subj_w[p] = [(s, c) for s, c in counter.most_common(25)]
        # Department hint: most over-represented mapped subject vs. everyone (lift).
        lift = {s: (c / ptotal) / (global_subj[s] / gtotal) for s, c in counter.items()
                if SUBJECT_DEPT.get(s) and c >= 20 and global_subj[s] > 0}
        if lift:
            plan_main_subj[p] = max(lift, key=lift.get)

    students, enrollments = build_students(
        rng, pool, plan_info, plan_subj_w, plan_main_subj, catalog, depts, real_ids, real_netids)
    personas = add_personas(students, enrollments, {c["code"] for c in catalog}, depts)
    programs = load_programs(src / "Programs and Program Accounts.csv", rng)

    used_subj = {c["subject"] for c in catalog}
    dataset = {
        "meta": {
            "generated_by": "generate/generate_dataset.py", "seed": SEED,
            "synthetic_students": True,
            "note": "Course codes, departments and programs are real; students, names, ids and survey answers are synthetic.",
        },
        "students": students,
        "personas": personas,
        "enrollments": enrollments,
        "courses": catalog,
        "departments": [
            {"department_id": k, "name": v, "has_courses": k in {SUBJECT_DEPT[s] for s in used_subj if SUBJECT_DEPT[s]}}
            for k, v in sorted(depts.items())
        ],
        "programs": programs,
    }

    # ---- PII check: no real id or netID may appear in the output ----
    text = json.dumps(dataset)
    tokens = set(re.findall(r"\b\d{8}\b", text))
    leaked = tokens & real_ids
    # Compare string VALUES (JSON keys excluded) against real netIDs, case-insensitively.
    # Real netIDs include plain words ("art", first names), so a blanket match is noise; check
    # every value containing a digit (netID-shaped), plus all student net_id/email fields.
    def _values(o):
        if isinstance(o, dict):
            for v in o.values():
                yield from _values(v)
        elif isinstance(o, list):
            for v in o:
                yield from _values(v)
        elif isinstance(o, str):
            yield o
    real_netids_l = {n.lower() for n in real_netids}
    leaked_net = {v for v in _values(dataset) if any(ch.isdigit() for ch in v) and v.lower() in real_netids_l}
    leaked_net |= {s[k].split("@")[0].lower() for s in students for k in ("net_id", "email")
                   if s[k] and s[k].split("@")[0].lower() in real_netids_l}
    if leaked or leaked_net:
        sys.exit(f"PII CHECK FAILED: ids={sorted(leaked)[:5]} netids={sorted(leaked_net)[:5]}")

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text)
    report = {
        "students_rows": len(students), "distinct_students": len({s['student_id'] for s in students}),
        "terms": dict(Counter(s["term"] for s in students)),
        "colleges": dict(Counter(s["college"] for s in students)),
        "courses": len(catalog), "subjects": len(used_subj),
        "departments": len(dataset["departments"]), "programs": len(programs),
        "program_types": dict(Counter(p["program_type"] for p in programs)),
        "plans_in_pool": len(pool), "min_k": MIN_K,
        "size_bytes": out.stat().st_size, "pii_check": "passed",
    }
    (out.parent / "generation_report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
