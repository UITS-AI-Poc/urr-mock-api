# CatCloud research mock GUI

A local GUI that follows the current prototype (researchopportunities.netlify.app, student side) and talks to the mock API.
It exists so you can verify the API data and the persona -> NSIF lookup -> `POST /matches` flow in a real UI.

```bash
cd gui
python3 serve.py              # proxies to the deployed AWS API; needs a valid SSO session
python3 serve.py --local      # no AWS: runs the bundled Lambda handler in-process (data/handler in this repo)
```

Open http://127.0.0.1:8765. Python 3 standard library only; no build step.

**AWS mode.** `serve.py` fetches the API key with the AWS CLI (profile `aipoc-admin`, `us-west-2`) and adds it as `x-api-key`
to every `/api/v1/*` request server-side. The key never reaches the browser or any file. If the SSO token has expired, run
`aws sso login --profile aipoc-admin` first. To skip the CLI, set `URR_MOCK_API_KEY`. Other options: `--base-url`, `--key-id`, `--profile`, `--port`.
It binds to 127.0.0.1 only.

## What the screens call

| Screen | Calls |
|---|---|
| Persona selector ("Viewing as") | `GET /students/demo-sample` (personas), then `GET /students/by-netid/{net_id}` |
| Home heads-up, Explore, Chat | `POST /matches` with the NSIF record + type preferences |
| Opportunities (programs) | `GET /programs` |
| Project detail, Faculty profile | `GET /faculty/{id}` |
| Browse all | `GET /faculty?q=&page=` |

The "API calls" button (bottom right) lists every request with status and timing; click one to see its response.
"mock scores" shows the heuristic score and signal breakdown (the prototype deliberately does not show scores).

## Differences from the prototype

- Matches come from the mock heuristic over 485 real researchers, so counts are larger than the prototype's curated three, and
  Banerjee/Kobourov (in the prototype) are not in the feed.
- "Active project" vs "Open to mentoring" is a GUI convention: projects generated from the researcher's own interests are "Active";
  those that fell back to the department name are "Open to mentoring".
- Chat is scripted; its answers only set the Paid/Volunteer/For-credit preferences sent to `/matches`.
- Respond / apply / save / reminders / feedback are stored in this browser's localStorage only (the API is read-only).
- Not built: Services/Events/News/Calendar, Agenda and tasks, the faculty-side screens (review queue, availability), and the faculty persona.
