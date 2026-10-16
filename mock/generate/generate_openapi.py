"""Write mock/openapi.json (OpenAPI 3.0.3) describing the mock API.

Usage: python3 -I generate_openapi.py --out ../openapi.json [--server https://.../prod/api/v1]
Schemas mirror services/nsif/models.py for the NSIF routes; extension schemas mirror the data
produced by generate_dataset.py / generate_faculty_projects.py.
"""

import argparse
import json

S = "string"


def obj(props, required=None, desc=None):
    o = {"type": "object", "properties": props}
    if required:
        o["required"] = required
    if desc:
        o["description"] = desc
    return o


def arr(items):
    return {"type": "array", "items": items}


def ref(name):
    return {"$ref": f"#/components/schemas/{name}"}


def nul(t, **kw):
    return {"type": t, "nullable": True, **kw}


STR_LIST = arr({"type": S})
INT_MAP = {"type": "object", "additionalProperties": {"type": "integer"}}

SCHEMAS = {
    "NSIFStudentResponse": obj({
        "student_id": {"type": S}, "term": {"type": S, "example": "F25"},
        "term_year": nul("integer"), "term_season": nul(S, enum=["Fall", "Spring"]),
        "full_name": nul(S), "first_name": nul(S), "last_name": nul(S), "email": nul(S),
        "net_id": nul(S), "college": nul(S), "department": nul(S), "plan": nul(S),
        "sub_plan": nul(S), "campus": nul(S),
        "career_interests": {**STR_LIST, "description": "Active career_* flag names"},
        "experience_preferences": {**STR_LIST, "description": "Active exp_* flag names"},
        "involvement_interests": {**STR_LIST, "description": "Active inv_* flag names"},
        "career_othertext": nul(S), "exp_othertext": nul(S), "inv_othertext": nul(S),
        "research_domains": {**STR_LIST, "description": "Derived from career flags (CAREER_TO_DOMAINS)"},
    }, ["student_id", "term"]),
    "NSIFStudentListResponse": obj({
        "students": arr(ref("NSIFStudentResponse")), "total": {"type": "integer"},
        "page": {"type": "integer"}, "page_size": {"type": "integer"}}, ["students", "total", "page", "page_size"]),
    "NSIFFilterParams": obj({
        "term": nul(S), "college": nul(S, description="Case-insensitive substring match"),
        "career_interests": {**STR_LIST, "description": "AND: student must have all"},
        "experience_preferences": {**STR_LIST, "description": "AND: student must have all"},
        "research_domains": {**STR_LIST, "description": "OR: student must have at least one"},
        "page": {"type": "integer", "minimum": 1, "default": 1},
        "page_size": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20}}),
    "NSIFStatsResponse": obj({
        "total_students": {"type": "integer"}, "terms": INT_MAP, "colleges": INT_MAP,
        "career_interests": INT_MAP,
        "experience_preferences": {**INT_MAP, "description": "Omits F21-only exp_employment / exp_coop (as the real API does)"},
        "research_domains": INT_MAP}, ["total_students"]),
    "NSIFTermInfo": obj({"term": {"type": S}, "term_year": nul("integer"), "term_season": nul(S),
                         "count": {"type": "integer"}}, ["term", "count"]),
    "NSIFTermsResponse": obj({"terms": arr(ref("NSIFTermInfo"))}, ["terms"]),
    "NSIFDemoStudent": obj({
        "student_id": {"type": S}, "net_id": nul(S),
        "display_label": {"type": S, "example": "Aramis Vega - Computer Science - Science (F25)"},
        "first_name": nul(S), "last_name": nul(S), "college": nul(S), "plan": nul(S), "term": {"type": S},
        "persona_label": {"type": S, "description": "MOCK EXTENSION (personas only): selector label, e.g. 'Aramis, CS Student'"},
        "class_standing": {"type": S, "description": "MOCK EXTENSION (personas only): from UAccess in the prototype; not in NSIF"},
    }, ["student_id", "display_label", "term"]),
    "NSIFDemoSampleResponse": obj({"students": arr(ref("NSIFDemoStudent")), "total_in_db": {"type": "integer"}},
                                  ["students", "total_in_db"], "Personas are listed first, then a stratified sample."),
    "HealthResponse": obj({"status": {"type": S}, "total_students": {"type": "integer"},
                           "total_terms": {"type": "integer"}}, ["status", "total_students", "total_terms"]),
    "StudentCourseTerm": obj({
        "term": {"type": S}, "term_year": {"type": "integer"}, "term_season": {"type": S},
        "courses": arr(obj({"code": {"type": S, "example": "CSC 110"}, "subject": {"type": S},
                            "catalog_nbr": {"type": S}, "department_id": nul(S)}))}),
    "StudentCoursesResponse": obj({"student_id": {"type": S}, "terms": arr(ref("StudentCourseTerm"))}),
    "Course": obj({"code": {"type": S}, "subject": {"type": S}, "catalog_nbr": {"type": S},
                   "level": {"type": "integer"}, "department_id": nul(S),
                   "enrollment_total": {"type": "integer"}, "terms": STR_LIST},
                  desc="Real course codes; titles are not available in the source data."),
    "CourseList": obj({"courses": arr(ref("Course")), "total": {"type": "integer"},
                       "page": {"type": "integer"}, "page_size": {"type": "integer"}}),
    "Department": obj({"department_id": {"type": S}, "name": {"type": S}, "has_courses": {"type": "boolean"}}),
    "DepartmentList": obj({"departments": arr(ref("Department")), "total": {"type": "integer"}}),
    "Program": obj({
        "id": {"type": S}, "name": {"type": S}, "org_id": nul(S), "description": nul(S), "website": nul(S),
        "length": nul(S), "incentive": nul("boolean"), "topic": nul(S), "mentoring_information": nul(S),
        "location": nul(S), "eligibility": nul(S), "program_type": nul(S), "credit_types": STR_LIST,
        "format": nul(S), "audiences": STR_LIST, "start_date": nul(S, format="date"),
        "end_date": nul(S, format="date"), "application_active": nul("boolean"),
        "application_open": nul(S, format="date"), "application_closed": nul(S, format="date"),
        "application_url": nul(S)}, ["id", "name"]),
    "ProgramList": obj({"programs": arr(ref("Program")), "total": {"type": "integer"},
                        "page": {"type": "integer"}, "page_size": {"type": "integer"}}),
    "Project": obj({
        "project_id": {"type": S}, "title": {"type": S}, "description": {"type": S},
        "likely_tasks": STR_LIST, "tasks_note": {"type": S},
        "application_mode": {"type": S, "enum": ["conversational", "structured"]},
        "application_status": {"type": S, "enum": ["open", "rolling", "not_yet_open", "closed"]},
        "application_opens": nul(S, format="date"), "application_closes": nul(S, format="date"),
        "spots": nul("integer"), "incentive": nul(S), "credit": nul(S), "format": nul(S),
        "inferred": {"type": "boolean", "description": "Always true: the source has no project data"},
        "inferred_from": {"type": S, "enum": ["interests", "department", "none"]},
        "disclaimer": {"type": S}}, desc="SYNTHETIC project generated for the mock. Null for researchers "
                                          "who are not offering opportunities."),
    "_PROJECT_NULLABLE_MARKER": None,
    "FacultySummary": obj({
        "faculty_id": {"type": S}, "name": nul(S), "title": nul(S), "primary_department": nul(S),
        "college": nul(S), "research_interests": STR_LIST, "offering_opportunities": {"type": "boolean"},
        "opportunity_types": arr({"type": S, "example": "For credit"}), "majors_considered": STR_LIST,
        "research_locations": STR_LIST, "project": ref("Project")}),
    "Faculty": obj({
        "faculty_id": {"type": S}, "slug": {"type": S}, "url": {"type": S}, "name": nul(S), "title": nul(S),
        "email": nul(S), "graduate_faculty": {"type": "boolean"}, "research_interests": STR_LIST,
        "research_interests_raw": nul(S), "offering_opportunities": {"type": "boolean"},
        "prerequisite_courses": nul(S, description="Free text as entered by the researcher"),
        "majors_considered": {**STR_LIST, "description": "May contain run-together free text"},
        "opportunity_types": STR_LIST, "description": nul(S), "start_date": nul(S), "end_date": nul(S),
        "college": nul(S), "primary_department": nul(S), "affiliated_departments": STR_LIST,
        "research_locations": STR_LIST, "lab_website": nul(S), "project": ref("Project")},
        desc="Real data scraped from ur.arizona.edu on 2026-10-16, except `project` (synthetic)."),
    "FacultyList": obj({"faculty": arr(ref("FacultySummary")), "total": {"type": "integer"},
                        "page": {"type": "integer"}, "page_size": {"type": "integer"}}),
    "MatchPreferences": obj({
        "paid": {"type": "boolean"}, "volunteer": {"type": "boolean"}, "for_credit": {"type": "boolean"},
        "include_closed": {"type": "boolean", "default": False}}),
    "MatchRequest": obj({
        "student": {**ref("NSIFStudentResponse"), "description": "An NSIF record, as returned by the student lookup routes"},
        "preferences": ref("MatchPreferences"),
        "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 10}}, ["student"]),
    "Match": obj({
        "faculty": ref("FacultySummary"),
        "match": obj({
            "percent": {"type": "integer", "minimum": 30, "maximum": 98},
            "reasons": {**STR_LIST, "description": "Generated only from signals that fired"},
            "signals": {"type": "object", "additionalProperties": {"type": "number"},
                        "description": "Component scores 0..1: major, domains, department, experience, availability"}})}),
    "MatchResponse": obj({
        "student_id": nul(S), "matches": arr(ref("Match")), "total_candidates": {"type": "integer"},
        "meta": obj({"heuristic": {"type": "boolean"}, "note": {"type": S}})},
        desc="Mock heuristic; NOT the production recommender."),
    "Error": obj({"detail": {"oneOf": [{"type": S}, arr({"type": "object"})]}}, ["detail"],
                 "FastAPI-style error body (string for 404/405, list of validation errors for 422)."),
}


SCHEMAS.pop("_PROJECT_NULLABLE_MARKER")
SCHEMAS["Project"]["nullable"] = True  # OpenAPI 3.0: nullable must sit on the schema itself


def param(name, where="query", schema=None, desc=None, required=False):
    p = {"name": name, "in": where, "required": required or where == "path", "schema": schema or {"type": S}}
    if desc:
        p["description"] = desc
    return p


PAGE = [param("page", schema={"type": "integer", "minimum": 1, "default": 1}),
        param("page_size", schema={"type": "integer", "minimum": 1, "maximum": 100, "default": 20})]
ERR = {"404": {"description": "Not found", "content": {"application/json": {"schema": ref("Error")}}}}
ERR422 = {"422": {"description": "Validation error", "content": {"application/json": {"schema": ref("Error")}}}}


def ok(schema_name, desc="OK", array=False):
    s = arr(ref(schema_name)) if array else ref(schema_name)
    return {"200": {"description": desc, "content": {"application/json": {"schema": s}}}}


def get(summary, responses, params=None, tag="NSIF", desc=None):
    d = {"summary": summary, "tags": [tag], "responses": responses}
    if params:
        d["parameters"] = params
    if desc:
        d["description"] = desc
    return {"get": d}


def build(server):
    paths = {
        "/health": get("Health check", ok("HealthResponse")),
        "/terms": get("List available terms with counts", ok("NSIFTermsResponse")),
        "/stats": get("Aggregate statistics across all terms", ok("NSIFStatsResponse")),
        "/stats/term/{term}": get("Aggregate statistics for one term",
                                  ok("NSIFStatsResponse"), [param("term", "path", desc="e.g. F24")]),
        "/students/demo-sample": get(
            "Sample of students for the demo dropdown (personas first)", ok("NSIFDemoSampleResponse"),
            [param("count", schema={"type": "integer", "default": 100})]),
        "/students/by-netid/{net_id}": get("Latest-term record by netID", {**ok("NSIFStudentResponse"), **ERR},
                                           [param("net_id", "path", desc="e.g. aramis.demo")]),
        "/students/{student_id}": get("Latest-term record for a student", {**ok("NSIFStudentResponse"), **ERR},
                                      [param("student_id", "path")]),
        "/students/{student_id}/history": get("All term records for a student, newest first",
                                              {**ok("NSIFStudentResponse", array=True), **ERR},
                                              [param("student_id", "path")]),
        "/students/search": {"post": {
            "summary": "Search students with filters and pagination", "tags": ["NSIF"],
            "requestBody": {"required": True, "content": {"application/json": {"schema": ref("NSIFFilterParams")}}},
            "responses": {**ok("NSIFStudentListResponse"), **ERR422}}},
        "/students/{student_id}/courses": get("EXTENSION: a student's enrollments by term",
                                              {**ok("StudentCoursesResponse"), **ERR},
                                              [param("student_id", "path")], "Extension"),
        "/courses": get("EXTENSION: course catalog", {**ok("CourseList"), **ERR422},
                        PAGE + [param("subject"), param("q", desc="Substring of the course code"),
                                param("department_id")], "Extension"),
        "/departments": get("EXTENSION: departments", ok("DepartmentList"),
                            [param("has_courses", schema={"type": "boolean"}), param("q")], "Extension"),
        "/programs": get("EXTENSION: programs", {**ok("ProgramList"), **ERR422},
                         PAGE + [param("type"), param("q")], "Extension"),
        "/programs/{program_id}": get("EXTENSION: one program", {**ok("Program"), **ERR},
                                      [param("program_id", "path")], "Extension"),
        "/faculty": get("EXTENSION: researchers with their (synthetic) projects", {**ok("FacultyList"), **ERR422},
                        PAGE + [param("q"), param("department"), param("college"),
                                param("type", desc="Paid | Volunteer | For credit"),
                                param("status", schema={"type": S, "enum": ["open", "rolling", "not_yet_open", "closed"]})],
                        "Extension"),
        "/faculty/{faculty_id}": get("EXTENSION: one researcher (full record)", {**ok("Faculty"), **ERR},
                                     [param("faculty_id", "path", desc="The person slug, e.g. quinn-burke")],
                                     "Extension"),
        "/matches": {"post": {
            "summary": "EXTENSION: rank projects for an NSIF student record", "tags": ["Extension"],
            "description": "Pass the record returned by /students/by-netid/{net_id}. Mock heuristic; closed "
                           "projects are excluded unless preferences.include_closed is true.",
            "requestBody": {"required": True, "content": {"application/json": {"schema": ref("MatchRequest")}}},
            "responses": {**ok("MatchResponse"), **ERR422}}},
    }
    for p in paths.values():
        for op in p.values():
            op.setdefault("security", [{"ApiKeyAuth": []}])
            op["responses"].setdefault("403", {"description": "Missing or invalid x-api-key"})
    return {
        "openapi": "3.0.3",
        "info": {
            "title": "URR mock API",
            "version": "1.0.0",
            "description": ("Read-only mock of the NSIF student-interest service plus CatCloud extension endpoints. "
                            "Student data is synthetic; faculty are real (scraped from ur.arizona.edu on 2026-10-16); "
                            "projects and match scores are synthetic/heuristic. Operations tagged `Extension` do not "
                            "exist in the real NSIF service."),
        },
        "servers": [{"url": server}],
        "tags": [{"name": "NSIF", "description": "Ported from services/nsif/api/routes.py"},
                 {"name": "Extension", "description": "Mock-only endpoints for the CatCloud prototype"}],
        "security": [{"ApiKeyAuth": []}],
        "paths": paths,
        "components": {
            "securitySchemes": {"ApiKeyAuth": {"type": "apiKey", "in": "header", "name": "x-api-key"}},
            "schemas": SCHEMAS,
        },
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--server", default="https://nzm36p0h50.execute-api.us-west-2.amazonaws.com/prod/api/v1")
    a = ap.parse_args()
    json.dump(build(a.server), open(a.out, "w"), indent=2)
    print("wrote", a.out)
