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

### 2026-10-16 — Remote switched to the azedu identity
- User's edu identity is the SSH alias `github.com-azedu` (authenticates as GitHub user bbendick-azedu). Set origin to git@github.com-azedu:UITS-AI-Poc/urr-mock-api.git.
- `git ls-remote` fails: UITS-AI-Poc enforces SAML SSO and this SSH key is not authorized for the org. Needs the user to authorize the key (GitHub > Settings > SSH and GPG keys > Configure SSO > Authorize for UITS-AI-Poc). Not pushed. Whether the repo already exists is still unknown (SSO error hides it).
- Commits so far are authored with the default git identity (bbendick@gmail.com), not the edu identity — unresolved, user to decide.

### 2026-10-16 — Pushed
- SSO authorization done by user; `git ls-remote` succeeded (repo existed, empty). Pushed main (63c107b) to git@github.com-azedu:UITS-AI-Poc/urr-mock-api.git. Verified: remote HEAD == local HEAD; fresh clone has 18 files, 0 from s3-data/. Repo visibility not checked.

### 2026-10-19 — Personas replaced with the prototype's dropdown students
- Investigated: the prototype (researchopportunities.netlify.app) changed since 2026-10-16 — no more iframe; a "Viewing as" dropdown (#personaSelect) now lists Jordan Alvarez (Sophomore, Psychology & Neuroscience), Amara Johnson (Freshman, Physiology), Diego Ramirez (Junior, Mechanical Engineering), Mei Tanaka (Freshman, Computer Science), plus "Dr. Stephen Cowen — Faculty, Psychology" (a faculty view, NOT a student; no persona created for it). Read persona definitions (major, interest, blurb, prefer, expected matches) from the page script.
- Changed: replaced the 6 placeholder personas (Aramis, Steve, Priya, Maya, Tomas, Dana) with these 4 in generate_dataset.py. Netids jordan/amara/diego/mei `.demo` (plain first names are real netIDs; PII check stays strict). `plan` uses real PeopleSoft descriptions, so it differs from the prototype's display text: Jordan -> "Neuroscience & Cognitive Sci", others match; the prototype's string is kept in persona `major_display`. Persona entries gained persona_id, blurb, preferences (volunteer/paid/for_credit from the prototype's `prefer`); demo-sample exposes them as additive fields; OpenAPI + tests updated. Freshmen get one term of enrollments, others two.
- Added subject AME -> dept 2305 (Aerospace & Mechanical Engr) so Diego has real mechanical-engineering courses. Side effect: catalog grew (50 subjects, 907 courses) and ALL synthetic students were redrawn (216 term rows, 154 distinct students), deterministic from the seed.
- Tests: 18 pass. Spec valid; all 216 student records and demo-sample validate.
- Fidelity check against the prototype's hardcoded expected matches (NOT a pass): Banerjee and Kobourov are not in the scraped feed at all (prototype faculty come from elsewhere/invented); Cowen, Cai, Gomez, Zeng are. Heuristic ranks: Jordan -> Cai #1 but Cowen #14 and Gomez absent; Amara -> Cowen #19, Cai #13; Diego -> Zeng #14, Cowen #54; Mei -> Zeng #23, Cowen #33. Reasons found: Gomez's majors_considered is run-together text with abbreviations (NSCS, SLHS) the matcher can't read; research_interests are comma-split paragraph fragments; matcher uses plan only (not NSIF department) and has no stemming/synonyms. NOT tuned — deciding whether to rig/tune toward the prototype's narrative is the user's call.
- NOT deployed: live API still serves the old personas. Changes are uncommitted locally and not pushed.

### 2026-10-19 — Local GUI (mock/gui) built and tested in --local mode
- User asked for a GUI based on the prototype's "Opportunities" screens, runnable locally against the AWS APIs, for verification.
- Re-read the prototype (it changed again): it now says matches are "explained in plain language, not scored" — the GUI leads with the reasons and hides the percent behind a "mock scores" toggle. Student-side pages: home, opportunities shell, explore, chat, project detail (conversational/structured), respond, apply, faculty profile. Faculty-side (fac-*) pages and the Cowen faculty persona are out of scope (need writes).
- Built `mock/gui/` (vanilla JS, no build): serve.py (stdlib; serves static files + proxies /api/v1/* adding x-api-key server-side; `--local` runs the bundled handler in-process; binds 127.0.0.1; blocks serve.py and path traversal), index.html, styles.css, app.js, README.md. Key comes from `aws apigateway get-api-key` (profile aipoc-admin) or URR_MOCK_API_KEY; never reaches the browser or a file. "API calls" drawer shows every request/response.
- Handler change: demo-sample now keeps persona order from the dataset (was alphabetical; prototype lists Jordan first). 18 tests pass.
- Tested via the in-app browser against `--local` only: persona flow (demo-sample -> by-netid -> POST /matches), Explore filters/render, project detail, conversational respond -> review -> submit -> Messages, structured apply (resume-required check), Opportunities chips (Research/Leadership/Volunteer), Browse (485 researchers, paged), scripted chat -> explore. No console errors. NOT yet verified: AWS mode (needs a valid SSO session), visual review beyond the Explore screen, mobile layout, Internship chip.
- AWS SSO token expired overnight ("Token has expired and refresh failed"); user must run `aws sso login --profile aipoc-admin` (the CLI never auto-triggers login). Because of this the live API still serves the OLD personas — redeploy (cdk diff, then deploy) is still pending, and the GUI shows a banner if the API lacks persona_id.
- Known caveats: counts differ from the prototype (94 matches for Jordan vs its curated 3); fewer cards link to "project" than "profile" because Active/Mentoring is a GUI convention derived from inferred_from; synthetic dates are compared to the real current date so "closes soon" drifts as time passes. Changes uncommitted and unpushed.

### 2026-10-19 — Redeployed new personas; GUI verified in AWS mode
- User ran `aws sso login --profile aipoc-admin` (token had expired). `cdk diff` showed a single change (Lambda code package replaced; no IAM/API/key changes); deployed (17s). Live API now serves the four prototype personas (jordan/amara/diego/mei, `.demo` netids) in prototype order, 216 student records.
- `serve.py` (AWS mode, key fetched via CLI server-side) is running on 127.0.0.1:8765 started from this session. Browser check after a real reload: mode "AWS", no banner, demo-sample -> by-netid -> POST /matches all 200 (192/159/458 ms); switching Diego/Mei/Jordan gives persona-specific type chips and result counts (61/94/94), 0 failed calls. Note: a hash-only navigation does not reload the page, so the mode label can look stale until a real reload (cosmetic).
- Still uncommitted/unpushed (handler, data, personas, openapi, GUI).

### 2026-10-19 — Committed and pushed
- Commit 0c8e96a (personas from the prototype + local GUI) pushed to origin/main (git@github.com-azedu:UITS-AI-Poc/urr-mock-api.git); remote HEAD matched local HEAD after fetch. Staged set checked first: no s3-data/, outputs.json, venvs or build output; secret-pattern scan clean (GUI holds only the API key id, not the value).

### 2026-10-19 — faculty.json tracking decision
- User asked whether faculty.json is gitignored. It is not: `s3-data/ur-researchers/researchers.json` (raw scrape) is ignored, but `mock/lambda/data/faculty.json` (generated, must ship with the Lambda) is tracked and on origin/main with 485 real names + emails (public on ur.arizona.edu).
- Decision: keep it tracked. User confirmed the GitHub repo UITS-AI-Poc/urr-mock-api is private. Rejected for now: stripping emails, or untracking and generating at deploy time (would need s3-data on the build machine and a history rewrite). Revisit if repo visibility ever widens.

### 2026-10-27 — CDK app switched from manual .venv to uv
- Replaced `cdk/requirements.txt` with `cdk/pyproject.toml` (same two deps: aws-cdk-lib==2.273.0, constructs>=10,<11); `uv sync` generated `cdk/uv.lock` (not gitignored) and a uv-managed `.venv/` (still gitignored, but no longer manually created/activated).
- `cdk.json` app entry changed from `.venv/bin/python app.py` to `uv run app.py`. Verified `cdk synth --profile aipoc-admin` produces the same template as before.
- README redeploy instructions updated to drop `source .venv/bin/activate` / `pip install -r requirements.txt` in favor of `uv sync`. Not deployed; this is a tooling-only change, not committed/pushed yet.

### 2026-10-27 — Deprecated Lambda logRetention replaced with explicit LogGroup
- `cdk diff` surfaced a jsii deprecation warning on `aws_lambda.Function#logRetention` (removed in a future major; works today via a hidden custom-resource Lambda that calls PutRetentionPolicy after deploy). Also hit a separate, unrelated jsii warning about running on untested Node v26 — user chose to fix that for real (brew-swap + pin node@22) rather than silence it; not done in this session, just advised.
- `mock/cdk/urr_mock_stack.py`: replaced `log_retention=logs.RetentionDays.ONE_WEEK` with an explicit `logs.LogGroup` (`RemovalPolicy.DESTROY`, same retention) passed via the function's `log_group=`. `cdk diff --profile aipoc-admin` confirmed the only change is removing the old custom-resource Lambda/role/policy and adding the real LogGroup + the function's LoggingConfig — no replacement of the function itself. Not deployed yet.

### 2026-10-27 — gitleaks check ahead of making the repo public
- Ran `gitleaks detect` on full git history (7 commits): no leaks. A working-tree-only scan flagged 3 false positives (Lambda asset zip hash misread as a generic API key) in `mock/cdk/cdk.out/`, which is gitignored build output, never committed.
- Gitleaks only catches credential-shaped secrets, not PII — flagged that `mock/lambda/data/faculty.json` (485 real names/emails, tracked, decided 2026-10-19 to keep tracked "while the repo is private") is the actual blocker for going public, not anything gitleaks finds.

### 2026-10-27 — Synthesized faculty identity; faculty.json untracked
- User asked to desensitize faculty identity so the repo can go public: keep real title/department/interests/majors/prerequisites/courses (not identifying on their own) but replace name and email with synthetic values.
- Added `mock/generate/generate_faculty_synth.py`: deterministic per-slug synthetic name/email (seeded hash of the real slug, so regeneration is stable), regenerates slug/url/faculty_id/project_id from the new name, and regexes the old surname out of `project.title`/`project.description` (the only place generate_faculty_projects.py had written `"<Lastname> group"` into prose) and replaces it with the new surname. Email domain is `mock.example.edu`, deliberately not arizona.edu.
- Verified: no synthetic name/email collides with any real one, and no `arizona.edu` string survives in any synthetic record. One class of false positive while checking: synthetic surnames coincidentally matching real *institution* names in department titles (e.g. "The Norton School of Human Ecology", a real UA school name, not the researcher's own identity) — left as is, since department names are intentionally kept real.
- `lambda/handler.py` now loads `data/faculty-synth.json` instead of `data/faculty.json`. `generate_openapi.py` updated (example slug, spec description wording). `openapi.json` regenerated; 18 tests pass.
- `mock/lambda/data/faculty.json` removed from git tracking (`git rm --cached`, file kept on disk — still needed locally as the input to generate_faculty_synth.py) and added to the root `.gitignore`. `faculty-synth.json` is the new tracked/served file. README updated (directory map, regen steps, provenance table) to describe the real scrape as a gitignored intermediate and faculty-synth.json as what ships.
- Not committed, not pushed, not redeployed — the live API still serves the old real-identity faculty.json until a redeploy.

### 2026-10-27 — Deployed synthetic faculty identity + LogGroup fix; verified live
- `cdk diff --profile aipoc-admin`: only the Lambda code asset hash (new bundle with faculty-synth.json + urr_mock_stack.py changes) and the LogGroup swap from the prior entry; no IAM/API/key changes. Deployed (`cdk deploy --require-approval never`), ~54s.
- Verified against the live API (key fetched via `aws apigateway get-api-key`): no-key request still 403; `/faculty?page_size=1` returns `casey-underwood` / "Casey Underwood" (was "Quinn Burke" pre-deploy) with description text correctly rewritten to "The Underwood group"; full record email is `casey.underwood@mock.example.edu` (no `arizona.edu`); `/health` unchanged (216 students, 9 terms); persona flow (`students/by-netid/jordan.demo` -> `POST /matches`) returns a synthetic faculty name in the top match with real department/interest text.
- Re-ran `gitleaks detect --no-git` on `mock/lambda/` post-deploy: no leaks. Confirmed no faculty email in the served file contains `arizona.edu`.
- Still open: not committed/pushed (working tree has the faculty.json untracking, uv/cdk changes, and this deploy's source changes); repo visibility (public) decision itself still pending on the user.

### 2026-10-27 — Committed, pushed, repo made public
- Before committing, found the faculty-synth anonymization was incomplete: scraped free-text fields (`research_interests_raw`, `description`, `prerequisite_courses`, `lab_website`) still named real researchers in self-authored bios ("Dr. Lai is interested in...", "Prof. Russell's research focuses on...") and personal lab URLs embedding real surnames (`riedel-kruse.arizona.edu`, `sites.arizona.edu/eggerslab`) for ~20+ of 485 records — `generate_faculty_synth.py` only touched the structured name/email fields and its own generated "`<Lastname> group`" phrase. Flagged this to the user before pushing/making public.
- User's call: that level of leakage is fine (self-published public bios/lab pages, already public on ur.arizona.edu, not new exposure). Not changed; left exactly as computed on 2026-10-27.
- Git had no author identity configured in this environment (`fatal: unable to auto-detect email address`). Prior commits on this repo used `Brett Bendickson <bbendick@arizona.edu>`; set that as **local** (not --global) repo config with the user's explicit go-ahead, then committed (d9e05f0: uv switch, logGroup fix, faculty synthesis) and pushed to `origin/main`.
- `gh` was not on PATH in the first shell invocation this session (fixed itself on retry — environment quirk, not resolved/explained). `gh repo edit UITS-AI-Poc/urr-mock-api --visibility public --accept-visibility-change-consequences` run per the user's explicit instruction; confirmed via `gh repo view`: visibility is now PUBLIC.

### 2026-10-29 — Root README.md
- Repo had no root README (only `mock/README.md`). Added `README.md` at the repo root documenting every route: 9 NSIF routes, 8 extension routes (courses, departments, programs, faculty, matches), and the local GUI server's routes (`/`, `/__config`, `/api/v1/*` proxy). Parameters, defaults, and error behavior were read from `mock/lambda/handler.py` and `mock/gui/serve.py`, not from the old README.
- Per the user, the README points to the API key's Stache entry (https://stache.arizona.edu/entry/638738a3d38ce5c8092f8b7996fa2941) and does not contain the key. I did not open the Stache page or fetch the key.
- Not verified: the endpoint descriptions were not exercised against the live API in this session. Not committed or pushed.

### 2026-10-29 — Flatten `mock/` into the repo root
- User's request: the repo (origin `UITS-AI-Poc/urr-mock-api`) should hold the former `mock/` contents at its root. Done with plain `mv` (so gitignored files such as `lambda/data/faculty.json` moved too), staged so git records renames. `mock/` removed.
- Root `README.md` conflict: user chose to keep `mock/README.md`. The route-by-route root README written earlier today is saved untracked as `README.root.md` (its `mock/...` links are stale); not merged, not decided what to do with it.
- Fixed `mock/` path references: `.gitignore` (faculty.json), README/gui README commands, docstrings in generate/*.py and lambda/handler.py. `../../s3-data` became `../s3-data` (same directory as before). `generated_by` in `lambda/data/dataset.json` still says `mock/generate/...` until the dataset is regenerated; not edited by hand.
- `cdk/.venv` was deleted and recreated with `uv sync` because the move breaks venv paths. 18 unit tests pass. `cdk synth` not re-run.
- `urr-aws-aisdlc/` is an untracked sibling that was already in the repo dir; left untouched. Not committed or pushed.

### 2026-10-29 — Correction: repo lives in `urr/mock/`, not `urr/`
- The previous entry misread the request. Intended layout: `urr/` is a plain directory (not a repo) containing `mock/` (the `urr-mock-api` repo, former `mock/` contents at its root) and `urr-aws-aisdlc/` (separate, outside the repo).
- Fix: moved everything (including `.git`, `.gitignore`) from `urr/` into `urr/mock/`; `urr-aws-aisdlc/` stays in `urr/`. Reverted `s3-data` doc paths to `../../s3-data` (raw data sits in `urr/`, outside the repo). Other path fixes from the previous entry stand. Tests pass. Not committed or pushed.
