# Phase 8 — Backend Deploy to Render

## Objective

Move the FastAPI backend off the developer laptop onto a
permanent HTTPS URL. Point the deployed Vercel frontend at
Render instead of an ngrok tunnel. Make the system independent of
the developer's machine being on.

## Service

- **URL**: https://voice-agent-bhnm.onrender.com
- **Region**: Singapore
- **Instance**: Free tier (spins down after 15 minutes idle)
- **Runtime**: Python 3.11.9 (pinned via `.python-version`)

## Commits

| Hash | Title |
|---|---|
| <hash> | chore(deploy): requirements.txt and Render blueprint |
| <hash> | fix(deploy): make voice_agent importable and pin Python 3.11 |
| <hash> | fix(deps): boto3 not boto in runtime dependencies |

## What was built

### `requirements.txt`

Generated from `pyproject.toml`. Render's default build command
is `pip install -r requirements.txt`, which is simpler than
installing the package itself via `pyproject.toml`.

### `render.yaml`

Blueprint describing the web service: Python runtime, Singapore
region, health check on `/health`, uvicorn start command binding
to `$PORT`. Secrets are declared with `sync: false` so Render
prompts for the values during first deploy rather than reading
them from the file.

**Note**: `render.yaml` is only read when a service is first
created. Subsequent changes must be made in the dashboard. This
is documented behavior, not a bug.

### `.python-version`

Pins Python 3.11.9. Render's Python runtime does not honor
`PYTHON_VERSION` from `render.yaml`; the `.python-version` file
is the supported mechanism.

### CORS and callback URLs

`FRONTEND_ORIGINS` (comma-separated) allows both localhost and
the Vercel deployment. `PUBLIC_BASE_URL` lets the backend derive
its own Vobiz callback URLs instead of requiring them in the
request body.

## Bugs found and fixed during the first deploy

### Bug 1 — `ModuleNotFoundError: No module named 'voice_agent'`

The project uses a `src` layout. `uvicorn voice_agent.api.server:app`
needs `src/` on Python's module search path, but `pip install -r
requirements.txt` does not add it. Locally this works because the
pyproject.toml editable install wires the path; Render's build
environment only runs the requirements install.

Fix: append `pip install -e .` to the build command.

### Bug 2 — Python version default

Render defaulted to 3.14.3, newer than any version this project
was tested on. `PYTHON_VERSION` in `render.yaml` was not honored.
The `.python-version` file fixed it.

### Bug 3 — `boto` vs `boto3`

The runtime manifest declared `boto>=1.35.0`. `boto` is the
deprecated boto 2.x library. The code imports `boto3` (see
`r2_client.py:11` and `retry.py` which handles
`botocore.exceptions.ClientError`).

Masked locally because `pyproject.toml` declares
`boto3-stubs[s3]` in the dev extras, which pulled the real
`boto3`. On Render, only runtime dependencies are installed.

Fix: `boto3>=1.35.0` in both `requirements.txt` and
`pyproject.toml`.

## Free tier behavior

Render spins the free service down after 15 minutes without
inbound traffic. The next request wakes it in about 60 seconds.

**Mitigation**: A cron job pinging `/health` every 10 minutes
prevents the sleep. Deferred to Phase 9.

## Validation

The critical test: **does the deployed system work without the
developer's laptop?**

- uvicorn stopped on the laptop
- ngrok stopped on the laptop
- Deployed frontend at https://voice-agent-ochre-two.vercel.app
- Placed a call from the New Call page
- Phone rang
- Greeting played
- Call appeared in the Calls list after 30 seconds

The system is now independent of the developer's machine.

## Known gaps

- **Cold start latency**: first call after 15 minutes idle takes
  ~60 seconds to reach the agent. Cron ping mitigation is Phase 9.

- **No CI/CD**: Render auto-deploys on push to main, but there is
  no pre-deploy test run. A failing test would still deploy.

- **Free tier memory**: 512 MB. Under heavy concurrency the
  service could OOM. Acceptable for the demo; paid tier for
  production.
