# Deployment guide (prepared, **not deployed**)

AEGIS runs as **one web service**: FastAPI serves the API and the built React app on the same origin. It is
simulation-only, it does not connect to real equipment, and it never exposes an operational control API.

## 1. Local development

```bash
pip install -r backend/requirements-dev.txt
```
```bash
npm --prefix frontend install
```
```bash
npm --prefix frontend run build
```
```bash
python -m uvicorn aegis.api:app --app-dir backend --port 8000
```

This serves http://127.0.0.1:8000. For hot-reloading frontend work, also run `npm --prefix frontend run dev` and use
http://localhost:5173, which proxies `/api` to port 8000.

## 2. Run the production configuration locally (no Docker needed)

Run this after building the frontend:

```bash
cd backend && AEGIS_ENV=production PORT=8000 AEGIS_BASIC_AUTH_USER=judge AEGIS_BASIC_AUTH_PASSWORD=change-me python -m aegis
```

On Windows PowerShell, set the variables with `$env:AEGIS_ENV="production"` and so on before running
`cd backend; python -m aegis`.

Check it is working:
- `http://127.0.0.1:8000/api/health` should return `{"ok": true, "env": "production", "access": "basic-auth", ...}`.
- Every other path should ask for the Basic-auth login.

## 3. Docker (the same image Render builds)

```bash
docker build -t aegis:local .
```
```bash
docker run --rm -p 8000:8000 -e AEGIS_BASIC_AUTH_USER=judge -e AEGIS_BASIC_AUTH_PASSWORD=change-me aegis:local
```

- **Build.** The image is multi-stage: Node 20 builds the frontend, then Python 3.12-slim installs only the runtime
  requirements.
- **Runtime.** It runs as a non-root user, listens on `$PORT` (default 8000), and has a `HEALTHCHECK` on `/api/health`.

> **Remote container test.** `.github/workflows/container-smoke.yml` builds this Dockerfile on a GitHub-hosted Linux runner and runs
> `scripts/container_smoke.sh` against the running container: production start, `/api/health`, 401 without a login, the frontend and
> static bundle, oversized and invalid uploads, the campus A/B/C workflow with the gate and human approval, fail-closed access, a second
> container on a different `$PORT`, an invalid `AEGIS_LLM_TIMEOUT`, and no password in logs or image metadata. The script's logic was also
> run locally against non-Docker production servers (all checks passed). **A container is validated only when that workflow shows a
> successful run for the commit you intend to deploy.**

> **Status.** Docker was not available in the build environment, so **the image itself has not been built or run
> yet**. The same layout was verified without Docker, using a staged copy with a clean `npm ci` build, a
> runtime-only virtualenv, `AEGIS_ENV=production` and `$PORT`. Run the two commands above before the first deployment.

## 4. Configuration (environment variables; see `.env.example`)

| Variable | Default | Purpose |
|---|---|---|
| `AEGIS_ENV` | `development` | `production` disables `/docs` and the OpenAPI schema, disables dev CORS, and **fails closed** without access config |
| `PORT` / `AEGIS_PORT` / `AEGIS_HOST` | `8000` / `127.0.0.1` (`0.0.0.0` when `PORT` is set) | Listening address; the host platform sets `PORT` |
| `AEGIS_BASIC_AUTH_USER`, `AEGIS_BASIC_AUTH_PASSWORD` | unset | HTTP Basic auth on everything except `/api/health` |
| `AEGIS_ALLOW_PUBLIC` | unset | `true` allows an open production demo. Without this or Basic auth, production answers 503 |
| `AEGIS_MAX_UPLOAD_MB`, `AEGIS_MAX_UPLOAD_ROWS`, `AEGIS_MAX_DATASETS` | 5, 50,000, 20 | Upload and memory limits |
| `AEGIS_MAX_BENCH_SEEDS` | 100 (`render.yaml`: 20) | Caps CPU-heavy benchmark runs |
| `AEGIS_CORS_ORIGINS` | Vite dev origins | Only if a separate frontend origin is ever used |
| `ANTHROPIC_API_KEY`, `AEGIS_LLM_MODEL`, `AEGIS_LLM_TIMEOUT` | unset, `claude-haiku-5-5`, `10` | Optional LLM explainer and tool controller. Without a key the deterministic agent is used. The timeout is validated (0.5-60 s; invalid values fall back to 10). Provider errors, timeouts and bad output fall back visibly to the deterministic agent |

Secrets go **only** in the hosting dashboard, never in Git. `.env` is git-ignored.

## 5. What is lost on restart (no persistent storage)

The following live in process memory and are **lost** when the service restarts, redeploys or sleeps (Render free
instances sleep when idle):
- incident episodes and their Decision Proof Records
- the last benchmark, stress and replay results (`latest.csv`)
- uploaded datasets

Users should **download** proof records and CSV/JSON results they want to keep.

The committed files are part of the image and survive:
- `data/real/` sample
- scenario configuration
- `results/` (excluded from the image by `.dockerignore`, but kept in Git)

If saved records ever become a requirement, add a managed database or object storage. That was **not** added in this
sprint, because no current feature needs it.

## 6. Deploying later on Render (manual, after approval)

**Prerequisites:** a Render account with access to the GitHub repository `ParthavSatvik/AEGIS-3.0`. Nothing has been
authorised or deployed yet.

1. Merge the tested feature branch into `main`, push, and tag the release (see §7).
2. In Render: **New → Blueprint** → pick the repository. Render reads `render.yaml` and creates the `aegis-3` web
   service (Docker, health check `/api/health`, branch `main`).
3. When prompted, set `AEGIS_BASIC_AUTH_USER` and `AEGIS_BASIC_AUTH_PASSWORD`. These are strongly recommended for any
   public URL. Leave `ANTHROPIC_API_KEY` empty unless the LLM controller is wanted.
4. **Apply.** The first build runs the Dockerfile, and the service goes live only when `/api/health` responds.
5. Note the `*.onrender.com` URL Render assigns. No URL is hardcoded anywhere in the app.

**Redeploying.** `render.yaml` ships with `autoDeploy: false`, so nothing redeploys until you click **Manual Deploy**. Setting
`autoDeploy: true` makes **each push to `main` rebuild and redeploy automatically**; use it only once the image has been tested. To deploy manually, click
**Manual Deploy → Deploy latest commit**.

## 7. Change workflow (feature branch → main)

1. `git switch -c feat/<change>` from the latest `main`.
2. Make the change, then run:

```bash
cd backend && python -m pytest -q
```
```bash
cd backend && python -m ruff check aegis tests
```
```bash
npm --prefix frontend run typecheck
```
```bash
npm --prefix frontend run lint
```
```bash
npm --prefix frontend run build
```

3. Run the production configuration locally (§2) or the Docker image (§3), and go through the checklist in §8.
4. Push the branch, open a pull request, review it, and merge into `main`. Merging to `main` is what triggers
   redeployment.
5. Tag the release: `git tag -a release-vX.Y.Z -m "..."`, then `git push origin release-vX.Y.Z`.

## 8. Post-deployment checklist (run after every deployment)

1. **Health check.** `GET /api/health` returns `ok: true`, `env: production`, and `access: basic-auth`, or `public` if
   that was intended.
2. **Access control.** Without credentials, `/` returns 401, and an unknown `/api/x` returns a JSON 404.
3. **Data import.**
   - Real data → **Load bundled real NPP file**: 409 valid points, and a trend chart.
   - Uploading an invalid file is rejected with a reason.
4. **Incident workflow.** Load ★ design scenario (seed 42), then:
   - stale SoH is flagged, and forced Plan A is **BLOCKED (R1)**
   - Run decision cycle: A/z3 counterexample at 21%, V(probe) +5.40, gate A R1 / B PASSED / C R7
5. **Human approval.** B waits for approval and Run is locked. **Approve** → gate re-check PASSED → restored in
   29 sim-min.
6. **Runtime monitoring.** Benchmark → **Run stress suite**: D has 0 violations, 156 safe recoveries and 49 monitor
   stops.
7. **Second fault.** Inject `grid_tie_trip` and approve S, which is verified. Inject `b1_derate` and AEGIS **abstains**.
8. **Proof record.** The Proof record tab downloads JSON.
9. **Benchmark.** Run benchmark: H1/H3/H4 supported, H2 not supported. CSV and JSON downloads work.

## 9. Rollback

- **Fast rollback.** In the Render dashboard → service → **Deploys**, choose the last good deploy → **Rollback**.
- **Rollback through Git.** Revert on `main`:

```bash
git revert <bad-commit>
```
```bash
git push origin main
```

  With `autoDeploy` on, Render rebuilds the reverted code; otherwise click Manual Deploy.
- **To a tagged release.** Create a branch from the tag, e.g. `git switch -c hotfix release-v1.3.0`. Point Render's
  branch at it temporarily, or merge it to `main`.

All release tags (`release-v1.0` … `release-v1.3.0`) are on GitHub and stay unchanged.
