# URR mock API

Read-only mock of the NSIF student-interest service plus the endpoints the CatCloud research
prototype needs. REST API (API Gateway, API key required) -> one Python Lambda, deployed with CDK (Python), `us-west-2`.
Spec: [openapi.json](openapi.json) (OpenAPI 3.0.3).

```
./
  generate/   generate_dataset.py, generate_faculty_projects.py, generate_faculty_synth.py, generate_openapi.py, scrape_ur_researchers.py (one-off)
  lambda/     handler.py + data/dataset.json + data/faculty-synth.json
  cdk/        app.py, urr_mock_stack.py
  tests/      test_handler.py
```

## Student selector flow

1. `GET /api/v1/students/demo-sample` – personas come first (`persona_label`, `class_standing` are extra fields).
2. `GET /api/v1/students/by-netid/{net_id}` – the student's NSIF record (e.g. `jordan.demo`).
3. `POST /api/v1/matches` with `{"student": <NSIF record>, "preferences": {...}, "limit": 10}` – ranked projects.

Every request needs an `x-api-key` header. The key is stored in Stache:
<https://stache.arizona.edu/entry/638738a3d38ce5c8092f8b7996fa2941>. Do not commit it.

`preferences` (all optional): `paid`, `volunteer`, `for_credit`, `include_closed` (booleans).
Matching is a mock heuristic (plan / interest-domain / preference overlap), **not** the production recommender.

## Endpoints (all under `/api/v1`)

NSIF routes, ported from `services/nsif/api/routes.py` (same paths, response shapes, 404 `{"detail": ...}` and 422 behavior):

| Method | Path |
|---|---|
| GET | `/health`, `/terms`, `/stats`, `/stats/term/{term}` |
| GET | `/students/demo-sample`, `/students/{id}`, `/students/{id}/history`, `/students/by-netid/{net_id}` |
| POST | `/students/search` (AND career/experience, OR domains, substring college, page_size 1-100) |

Extensions (NOT in the real NSIF service):

| Method | Path |
|---|---|
| GET | `/students/{id}/courses`, `/courses?subject=&q=&department_id=`, `/departments?has_courses=&q=` |
| GET | `/programs?type=&q=`, `/programs/{id}` |
| GET | `/faculty?q=&department=&college=&type=&status=`, `/faculty/{faculty_id}` |
| POST | `/matches` |

List routes take `page` and `page_size`. CORS is open (`*`). There are no write endpoints.

## Regenerating data

The raw inputs live in `s3-data/` at the repo root, which is **not in this repo** (real student/staff identifiers, ~700 MB).
The committed `lambda/data/dataset.json` is a generated output, so the API can be redeployed without `s3-data/`.

`lambda/data/faculty.json` (real scraped names/emails + synthetic project) is an intermediate file, **not committed** —
it is gitignored because it carries real faculty names/emails. `generate_faculty_synth.py` turns it into
`lambda/data/faculty-synth.json` (real title/department/interests/majors/courses, but synthetic name/email, slug, and
faculty_id), which **is** committed and is what the Lambda actually serves.

```bash
cd generate
python3 -I generate_dataset.py --s3-data ../../s3-data --out ../lambda/data/dataset.json
python3 -I generate_faculty_projects.py --in ../../s3-data/ur-researchers/researchers.json --out ../lambda/data/faculty.json
python3 -I generate_faculty_synth.py --in ../lambda/data/faculty.json --out ../lambda/data/faculty-synth.json
python3 -m unittest discover -s ../tests -v      # from tests
```
`scrape_ur_researchers.py` is a one-off snapshot (2026-10-16) of ur.arizona.edu; it is cached and not part of the build.
Regenerating `faculty.json` requires `s3-data/ur-researchers/researchers.json` (the raw scrape) on the build machine;
`faculty-synth.json` alone is enough to run or redeploy the API.

## Deployed instance

- Base URL: `https://nzm36p0h50.execute-api.us-west-2.amazonaws.com/prod/api/v1` (stack `UrrMockApi`, account 557092275502)
- Every request needs the header `x-api-key`. OPTIONS preflight does not. Usage plan: 50 req/s, burst 100, 100k requests/month.
- Get the key value (do not commit it):

```bash
aws apigateway get-api-key --api-key p95shxgzr1 --include-value --query value --output text --region us-west-2 --profile aipoc-admin
```

```bash
curl -H "x-api-key: $KEY" https://nzm36p0h50.execute-api.us-west-2.amazonaws.com/prod/api/v1/students/demo-sample
```

Redeploy after changing data or the handler (review the diff first):

```bash
cd cdk                                     # uv sync first time; cdk.json runs the app via `uv run`
cdk diff --profile aipoc-admin
cdk deploy --profile aipoc-admin
```

A REST API is used instead of an HTTP API because HTTP APIs have no API keys. `cloud_watch_role` is disabled so the stack does not touch the account-wide API Gateway CloudWatch role.
Regenerate the spec with `python3 -I generate_openapi.py --out ../openapi.json`.

## Provenance: what is real and what is not

| Data | Status |
|---|---|
| Course codes (subject + catalog number) and which terms they ran | Real (classlist). No titles exist in the source. |
| Departments (id + name) | Real (staff-titles-enriched). Subject -> department mapping is hand-made. |
| Plans / colleges | Real PeopleSoft values (UA_SR_CAREER_PROG_PLAN); frequencies from active students. College strings may not match NSIF's spelling. |
| Programs | Sampled from "Programs and Program Accounts.csv"; HTML stripped. |
| Faculty (title, department, interests, majors, prerequisites, opportunity types) | Real, scraped from ur.arizona.edu (485 researchers). |
| Faculty **name and email** | **Synthetic.** The real scrape (with real names/emails) is gitignored; only `faculty-synth.json` (synthetic identity) is committed and served. |
| Faculty **projects** (title, description, tasks, application mode/status/dates, spots) | **Synthetic**, flagged `inferred: true`. The source has no descriptions or project data. |
| Students (ids, names, netIDs, survey answers, enrollments) | **Synthetic.** Enrollments drawn from plan->subject aggregates (>=50 real students), never from one real student. |
| Personas (6) | Synthetic and hand-set; names will change when the prototype defines them. |
| NSIF flag names | career/exp from `config.py`; inv_* from a real NSIF header row (varies by term in real data). |
| Match scores | Mock heuristic. |

A PII check in `generate_dataset.py` fails the build if a real 8-digit id or a netID-shaped value appears in the output.
Real netIDs include plain first names, so synthetic netIDs carry digits or `.demo`.
