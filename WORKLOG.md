# WORKLOG

## Current state
- Goal: mock backend (API Gateway + Lambda via CDK, static synthetic data) so the URR frontend can be built before the real data source exists.
- Plan under review (not yet approved). No code written yet.
- Open: CDK language, AWS region, frontend stack, whether to add non-NSIF endpoints (courses, departments, programs) — none exist in the NSIF repo service.

## Entries

### 2026-10-16 — Investigated NSIF service
- Read UA-AI2S/undergraduate-research-recommender `services/nsif` (routes.py, models.py, schema.py, config.py, normalizer.py) via `gh api`.
- 9 endpoints under `/api/v1`: health, terms, stats, stats/term/{term}, students/demo-sample, students/{id}, students/{id}/history, students/by-netid/{net_id}, POST students/search.
- Search semantics: AND on career/exp filters, OR on research domains, ilike on college, page_size 1..100.
- Decision (proposed, user leaning static + API Gateway + CDK): one Lambda over a bundled dataset rather than per-file S3 statics, because POST search needs logic. Rejected: API Gateway mock integrations only (cannot filter).

### 2026-10-16 — Investigated s3-data
- `classlist_urr_dec_19.csv`: 1.58M rows, cols EMPLID,STRM,CLASS_NBR,SUBJECT,CATALOG_NBR; 61,760 real EMPLIDs, 16,286 distinct (subject, catalog) courses, 352 subjects. STRM is PeopleSoft term code (e.g. 2244 = Fall 2024, 2261 = Spring 2026).
- `staff-titles-enriched.json`: 14,789 staff records, 465 distinct (employeePrimaryDept, deptName) pairs; contains real uid/emplId (not to be copied).
- `Programs and Program Accounts.csv`: 2,400 rows, 2,060 distinct programs. Mostly employer/job-posting style accounts; only ~67 typed "Research". The `Parent.Display_Name__c` column contains long description text for many rows (looks misaligned — cause unknown).
- `urr_active_students.csv` has real Plan/ClassStanding values (usable only as aggregate distributions). `emplid-netid.json` and active students are real PII — do not copy into the mock.

### 2026-10-16 — Decisions on mock scope and data
- User: Python CDK, us-west-2, append `--profile aipoc-admin` to all aws/cdk CLI commands. Aggregate-derived enrollments approved (no re-IDed real students).
- User clarified: s3-data is the raw "base"; the real pipeline does ingestion/processing between raw data and what the API serves. The mock must fill those processing steps in, not just echo raw rows.
- Findings used for the design: UA_SR_CAREER_PROG_PLAN.csv gives real plan code -> plan description and Acad Prog (college) description; urr_active_students.csv gives plan frequencies (aggregate only); staff-titles-enriched.json gives real dept id/name; programs CSV has ~173 typed rows (rest are job-posting style accounts); only inv_fsp is known by name for inv_* flags (others come from survey XLSX headers not in the repo — will be plausible/unverified).
- Not yet written: generator, Lambda, CDK. Nothing deployed.

### 2026-10-16 — Built dataset generator
- Wrote `mock/generate/generate_dataset.py`; output `mock/lambda/data/dataset.json` (~430 KB) + `generation_report.json`. 150 synthetic students / 206 term records (F21–F25), 877 real course codes (49 subjects), 465 real departments, 43 sampled programs (only 6 distinct "Research" typed programs exist after dedupe).
- Enrollments drawn from plan->subject aggregates (k>=50 real students, else college-level); no individual real course lists used.
- PII check: fails the build if any real 8-digit id appears anywhere, or any netID-shaped value (contains a digit) or student net_id/email matches a real netID. First attempt (match every string value) was too noisy: real netIDs include plain words ("art", first names). An earlier narrowing to net_id-only was blocked by the auto-mode classifier as weakening the check; replaced with the broader digit-shaped + net_id/email check. Residual risk: a synthetic first+last name could coincide with a real person (unavoidable).
- Assumptions/synthetic: survey answers, inv_* names (only inv_fsp verified), campus, course titles absent, college = UA_SR Acad Prog description as-is (real values, not necessarily NSIF's spelling).
- Next: Lambda handler, CDK stack, tests, README. Nothing deployed.

### 2026-10-16 — inv_* flags now verified
- Investigated: repo search for `inv_` found nothing; s3-data has none (CRM-34395.xlsx is Salesforce event attendance, no NSIF columns). Only `inv_fsp` was known from column_maps.py.
- User supplied a real NSIF header row. inv_* set: acadclubs, employment, fsp, health, leadership, culturalresource, internship, recsports, reslife, studentgov, sustainability, peermentor, firstgen, arts, relig, other (+ inv_othertext). Career (12) and exp (13) columns match config.py. Other columns seen: Campus, AcademicProgramLocation, IPEDSCohortDescription, IPEDSNewStudent, PreferredFirstName, opt_in (not exposed by the API models).
- Replaced guessed inv_* names in the generator with the real ones; inv_othertext now set when inv_other is active. Regenerated; PII check passed (215 term rows).
- Caveat: columns vary by term in the real data; this header is one term (which one is unknown), so older terms may have a different inv_* subset. Probabilities for each flag remain synthetic.

### 2026-10-16 — Gap analysis vs. CatCloud prototype (researchopportunities.netlify.app)
- Investigated: the site is a walkthrough with the whole app embedded as one data: URL iframe (hardcoded HTML, no network calls, no backend). Decoded and read all 14 screens.
- Screens: Opportunities shell (Recommended + programs list w/ Research/Internship/Leadership/Volunteer filters, program detail w/ eligibility/mentors/dates), Research Explore (blended matches), matcher chat, project detail, faculty profile, unconfirmed-researcher profile, two apply flows (conversational / structured w/ resume), outreach-email drafts, "not a fit" feedback, faculty review queue.
- Finding: the NSIF-shaped mock covers almost none of this. The prototype's core entities are faculty, projects/listings, match scores, student profile (UAccess major + class standing), applications/responses, saved, messages. NSIF only provides survey interests; programs data (CSV) covers only the Opportunities-shell list.
- Candidate real sources in s3-data (not yet inspected in depth): kmapFacultyProfiles.json (5,796 faculty w/ weighted research_interests; 'kmapId' + name), research-interests.json, bio.json, Faculty.csv, pubs, staff-titles-enriched (dept/title). Page says "531 real records" from a faculty research-availability feed — NOT found in s3-data (research-opportunities.json is actually awards data, 29 rows).
- Decision pending with user. No code changed.

### 2026-10-16 — Availability scraper (decisions + run)
- User decisions: the CatCloud prototype is the target UI; real faculty are OK in the mock; mock is read-only; pull availability from https://ur.arizona.edu/find/search-ua-researchers as a one-off script writing flat files.
- Investigated the source: Drupal table, 25 rows/page, 20 pages (page 20 empty); /find/ is not disallowed by robots.txt (only /search/). Each /person/<slug> page has the full record (title, email, interests, offering yes/no, prereqs, majors considered, types, description, start/end date, college, primary + affiliated depts, location).
- Wrote `mock/generate/scrape_ur_researchers.py` (1 req/s, identifiable UA, disk cache, resumable). Output: `s3-data/ur-researchers/{researchers.json,researchers.csv,scrape_report.json}`.
- Bug found in 5-record test: prerequisite_courses is free text, comma-splitting broke it ("Python, C, or ..."); now kept as a string. Majors/types/interests remain comma-split lists (unverified that no majors name contains a comma).
- Observed in test: description is often "No description given"; lab website rarely present. The prototype's rich project text (e.g. "What you'd likely be doing") is NOT in this source — that was written/inferred in the prototype. Full run started in background.
- Note: the prototype said "531 real records"; compare against the scrape count when done.

### 2026-10-16 — Scrape complete
- Result: 485 researchers (20 list pages, 0 failures) in `s3-data/ur-researchers/`; 484 offering opportunities. Fewer than the prototype's "531 real records" (cause unknown — different snapshot date or a different feed).
- Verified in raw HTML (not a parser bug): every record's "Description of Opportunity" is the literal "No description given", so description is null for all 485; lab_website is null for all (the prototype's lab links/descriptions did not come from this source). 214 have no research_interests, 26 no college, 6 end dates present.
- Majors considered contain generic values ("Any", "All"); no major names contain commas.

### 2026-10-16 — Faculty + mock project descriptions
- User decisions: mock covers ONLY the 485 scraped researchers (no kmap join, no unconfirmed-researcher set); project descriptions are mocked.
- Wrote `mock/generate/generate_faculty_projects.py` -> `mock/lambda/data/faculty.json` (~1.1 MB; 485 faculty real as scraped, 484 with a synthetic `project`). Per project: title, description, 3 likely_tasks (template by field bucket), application_mode (70% conversational / 30% structured), status (open/rolling/not_yet_open/closed relative to 2026-10-16), open/close dates + spots for structured, incentive/credit/format derived from real opportunity_types. All flagged `inferred: true` with a disclaimer; deterministic per slug.
- Scraper change: added `research_interests_raw` (free text, comma-splitting was lossy). Generator splits raw on bullets/;/, and drops fragments (>6 words or >50 chars), so some long interest phrases are omitted from titles.
- Known weaknesses: titles/descriptions are generic templates ("Research in X and Y"); 268 of 484 projects fall back to department as topic because interests are empty or unusable; "Role of gender and women"-style phrases appear verbatim; no match scores, no per-user state yet (read-only means saved/applications/queue are static fixtures, TBD).

### 2026-10-16 — Student selector design + personas
- User: the prototype will get a student selector dropdown (e.g. "Aramis, CS Student", "Steve, English Student"); this is the link between NSIF and the faculty/project endpoints. Flow agreed: selector -> NSIF lookup (demo-sample / by-netid) -> frontend POSTs the NSIF record to a new matching endpoint -> ranked projects. User: use any personas for now; real names come later from the prototype.
- Decision: new `POST /api/v1/matches` (name not dictated by the real design; user OK'd it). Stateless — frontend passes the NSIF record (+ optional chat preferences). Mock heuristic, not the real recommender; response will say so.
- Added 6 fixed personas to generate_dataset.py (Aramis CS, Steve English, Priya Nursing, Maya Business, Tomas Biology, Dana Psychology), F25 NSIF records + 2 terms of enrollments. `class_standing` lives in dataset["personas"], outside the NSIF shape (not in NSIF).
- PII check correctly rejected plain-first-name netIDs (maya, steve, priya, tomas are real netIDs); personas use `<first>.demo` instead. I did not weaken the check.
- Fixed 8 guessed course codes that weren't in the real catalog (generator silently drops codes not in catalog; no "SBS" courses survive the catalog filter). Dataset now 156 distinct students.
- Next: Lambda (NSIF routes + faculty/projects + /matches), CDK stack, tests, README.

### 2026-10-16 — Lambda, matcher, CDK built (not deployed)
- Wrote `mock/lambda/handler.py`: all 9 NSIF routes ported from routes.py to in-memory (term ordering, AND/OR search, stats incl. exp_employment/exp_coop omission, FastAPI-style 404/422), plus extension routes (/students/{id}/courses, /courses, /departments, /programs[/{id}], /faculty[/{id}]) and `POST /matches`. demo-sample returns personas first with extra `persona_label` + `class_standing` fields (additive, not in the real model).
- Matcher: weighted overlap of plan vs majors_considered (0.40), research-domain keywords vs faculty text (0.25), plan vs department (0.10), experience/preferences (0.15), availability (0.10) -> 30..98%. Closed projects excluded unless preferences.include_closed. Reasons are generated only from signals that fired.
- Data issue found while eyeballing matches (tests passing did not reveal it): 79/485 researchers typed majors_considered as run-together free text with no delimiters (source data, not a parser bug). Matcher treats entries >5 words as free text and doesn't quote them. Generic single-word overlaps ("management") are ignored.
- Known weakness: for personas with few matching faculty (e.g. Business), top results are "open to any major" labs at ~66%. Scores are plausible-looking, not validated against any ground truth.
- `mock/tests/test_handler.py`: 17 unittest cases pass (run without -I; -I strips cwd from sys.path).
- CDK (Python, aws-cdk-lib 2.273.0): `mock/cdk/` HttpApi + one greedy route ANY /api/v1/{proxy+} -> Lambda (python3.12, 512MB), CORS *, output ApiBaseUrl. `cdk synth --profile aipoc-admin` succeeds (account resolved from profile); packaged asset verified to contain data/*.json and answer an API Gateway v2 event. NOT bootstrapped, NOT deployed.
- Decision: single proxy route + in-Lambda routing instead of one API Gateway route per path (simpler; avoids API Gateway route-precedence reliance).
- Added `mock/README.md` (endpoints, regenerate, deploy, provenance table).
- Open: deploy approval (account/region confirmed us-west-2, profile aipoc-admin; bootstrap status unknown); the open API serves real faculty names/emails (public on ur.arizona.edu) with no auth; OpenAPI spec not written.

### 2026-10-16 — Deployed (REST API + API key) and OpenAPI spec
- Bootstrap: checked first — us-west-2 in account 557092275502 was already bootstrapped (CDKToolkit CREATE_COMPLETE, bootstrap version 32), so no bootstrap was run.
- Changed stack from HTTP API to REST API because HTTP APIs do not support API keys. Greedy resource api/v1/{proxy+} ANY (api_key_required) -> Lambda; OPTIONS preflight unauthenticated; CORS headers on gateway 4xx/5xx so a missing key shows as 403 not a CORS error; usage plan 50 rps/100 burst/100k per month. Set cloud_watch_role=False after `cdk synth` showed an AWS::ApiGateway::Account resource (would have modified an account-wide setting).
- Handler already accepted REST (payload v1) events; added a test (18 tests pass).
- First `cdk deploy --require-approval never` was blocked by the auto-mode classifier as a blind apply. Ran `cdk diff` first (all additive: Lambda, REST API, key, usage plan, 2 IAM roles, log retention; nothing modified/deleted), then deployed. Stack UrrMockApi deployed in ~55s.
- Live: https://nzm36p0h50.execute-api.us-west-2.amazonaws.com/prod/api/v1 ; API key id p95shxgzr1 (value fetched via aws apigateway get-api-key; not stored in the repo). Smoke test: no key -> 403, wrong key -> 403, valid key -> 200 on health/by-netid/demo-sample/matches, 404 and 422 bodies match FastAPI style, preflight 204 with CORS. First call with a valid key got 403 (usage-plan propagation delay; config verified correct, worked on retry). Two of my debugging aws commands failed because zsh does not word-split a "$P" flags variable — no effect on the deployment.
- OpenAPI: `mock/generate/generate_openapi.py` -> `mock/openapi.json` (3.0.3, 17 paths, 26 schemas, ApiKeyAuth). Validated with openapi-spec-validator, and every dataset record (221 students, 485 faculty, 43 programs, 877 courses, 465 departments) validates against its schema. Fixed a spec bug found that way: Faculty.project is null for 1 researcher; OpenAPI 3.0 needs `nullable` on the Project schema itself (nullable beside a $ref/allOf does not work).
- README updated with deployed URL, key retrieval, redeploy steps.
- Open: one shared key for all callers (rotate by replacing the ApiKey resource); real faculty names/emails are behind the key but still served; no WAF; frontend not built.

### 2026-10-16 — Git repo (local only so far)
- Initialized git at the project root (branch main), .gitignore excludes s3-data/ (real student/staff identifiers, ~700 MB), .venv, cdk.out, outputs.json, .claude/. Scanned staged files for secrets: none. 18 files committed (ae934e5).
- Remote git@github.com:UITS-AI-Poc/urr-mock-api.git does not exist / not visible; `gh repo create` failed: user bbendick lacks CreateRepository permission in UITS-AI-Poc. Not pushed. Did not fall back to another owner (user named this destination). Remote `origin` added locally.
- Open: someone with org rights must create the (private recommended) empty repo or grant access; then `git push -u origin main`.
