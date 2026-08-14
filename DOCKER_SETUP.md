# Docker Setup

Phase 6 adds a `docker-compose.yml` that runs the main app and all three
custom adapters as separate containers (one container per adapter, per D9).

**Current status:** a full `docker-compose up` run was verified working end
to end (all 4 containers healthy, adapters reachable, downloads succeeding).
The Docker deployment was then torn down (`docker-compose down --rmi all -v
--remove-orphans`) in favor of native (`start.bat`) local runs, since that's
faster to iterate on for day-to-day adapter development/debugging — no
image rebuild needed for a Python-only change. The plan is to redeploy via
Docker on a VPS later; this file's instructions remain the reference for
that. Nothing below changed as a result — `docker-compose.yml` and both
`Dockerfile`s are untouched on disk, so `docker-compose build && docker-
compose up` from this same project directory reproduces the verified setup.
Note the **Adapter URLs** section below — those `config.adapter_url` values
need to be switched from `localhost` back to the Compose service names
before that redeploy, the same way they'd need switching back to `localhost`
if you return to native running in between.

## Before first `docker-compose up`

`broll_engine.db` is bind-mounted from the project root into the `app`
container (`./broll_engine.db:/app/broll_engine.db`). Docker creates a
**directory** instead of a file if the host path doesn't exist yet, which
breaks SQLite. Make sure `broll_engine.db` already exists at the project
root before running `docker-compose up` (it does if you've run the app
locally at least once — Alembic/SQLAlchemy create it on first run).

## Uploaded local-folder libraries and adapter scripts

`local_folder` sources now store their media by upload (see
`docs/USER_GUIDE.md` §3/§5) rather than a typed host path, saved under
`local_libraries/<source_id>/` at the project root; custom-adapter script
uploads land under `CustomAdapters/uploaded/<source_id>/`. Both are bind-mounted
into the `app` container in `docker-compose.yml` so they persist across
`docker-compose down`/`up` instead of living only in the container's
writable layer. Unlike `broll_engine.db`, these are directories, so Docker
will create them on the host automatically if they don't exist yet — no
manual pre-creation needed.

## Adapter URLs: localhost vs. container names

This is the one setting you MUST change before running the app in Docker.

Locally (no Docker), each `custom_adapter` source's `config.adapter_url` in
the database points at `http://localhost:3000` (etc.) — the adapter runs as
a separate OS process on the same machine, so `localhost` resolves
correctly.

Inside Docker, `localhost` inside the `app` container refers to the `app`
container itself, not the adapter containers — they're separate network
namespaces. Each adapter is reachable by its **Docker Compose service
name** instead:

| Adapter      | Local URL               | Docker URL                        |
|--------------|--------------------------|------------------------------------|
| 40k.gallery  | `http://localhost:3000`  | `http://adapter-wh40k:3000`        |
| artvee.com   | `http://localhost:3001`  | `http://adapter-artvee:3001`       |
| loc.gov      | `http://localhost:3002`  | `http://adapter-loc:3002`          |

Update each `custom_adapter` `MediaSource.config.adapter_url` in the
Sources UI (or directly in the DB) to the Docker URL before running under
Compose. `adapter_script_path` (used for local auto-launch) is irrelevant
inside Docker — each adapter container starts its own script directly via
its Dockerfile `CMD`, so leave that field blank or ignore it for Docker
deployments.

## Commands

```bash
cd "D:\yt_vids\automation ecosystem\BRollGen"
docker-compose build
docker-compose up
```

Check status:

```bash
docker-compose ps
```

All four services should show `healthy` (adapters) or `running` (app —
the app itself has no healthcheck defined, only the three adapters do,
since `app`'s `depends_on: condition: service_healthy` only needs the
adapters ready before it starts).

## Known docker-compose v1 recreate bug

If a `docker-compose up` that recreates an existing container (e.g. after
adding a new volume mount) fails with `ERROR: for app 'ContainerConfig'` /
`KeyError: 'ContainerConfig'`, that's a known bug in docker-compose v1.29.2
itself, not a project bug — it mishandles reading the previous container's
config during recreate. Fix: `docker-compose down` then `docker-compose up`
(a full recreate instead of an in-place one sidesteps the bug). Longer
term, migrating to Docker Compose v2 (the `docker compose` subcommand,
bundled with current Docker Desktop / Engine installs) avoids this bug
entirely — same `docker-compose.yml`, just invoked as `docker compose ...`
instead of `docker-compose ...`.

## Full teardown

To stop and completely remove everything this compose file created
(containers, images built from it, volumes, network) without touching any
project files or the bind-mounted host data (`broll_engine.db`,
`local_libraries/`, `CustomAdapters/uploaded/`, `tmp/` — none of those live
in Docker):

```bash
docker-compose down --rmi all -v --remove-orphans
```

## Frontend build

The main `Dockerfile` copies `frontend/dist/` into the image — build the
frontend before `docker-compose build`:

```bash
cd frontend
npm run build
```
