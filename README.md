# Keitaro campaign manager

A small wrapper over the [Keitaro](https://keitaro.io) Admin API:

1. **Campaign creator.** Name, geo (`MX,AU,RO`) and an offer turn into a Keitaro campaign with two streams:
   stream 1 sends the listed countries to google.com, stream 2 sends everyone else to the offer.
2. **Stream offer editor** with a draft/publish flow. Add, Remove, Bring back and Pin change only a local
   draft (the stream turns yellow); **Push** publishes it to Keitaro, **Cancel** throws it away,
   **Fetch streams** syncs with what is live in Keitaro.

Stack: FastAPI, async SQLAlchemy 2, Alembic, PostgreSQL, httpx · React, Vite, TanStack Query · Docker Compose.

Design decisions, edge cases and open questions: [WALKTHROUGH.md](WALKTHROUGH.md).

## Quick start (Docker)

```sh
cp .env.example .env        # then put your Keitaro API key into KEITARO_API_KEY
docker compose up --build
```

Open http://localhost:8080. Migrations are applied automatically when the `api` container starts.

## Run without Docker

Requirements: Python 3.12+ with [uv](https://docs.astral.sh/uv/), Node 22+, PostgreSQL 15+.

```sh
cp .env.example .env               # KEITARO_API_KEY, and DATABASE_URL if not the default below
docker compose up -d db            # or use your own Postgres via DATABASE_URL

cd backend
uv sync
uv run alembic upgrade head        # migrations
uv run uvicorn app.main:app --reload --port 8000

cd ../web                          # in a second terminal
npm install
npm run dev                        # http://localhost:5173, proxies /api to :8000
```

Default `DATABASE_URL` is `postgresql+asyncpg://kcm:kcm@localhost:5432/kcm` (the compose `db` service).

## Migrations

Alembic lives in `backend/migrations`, the schema is defined in `backend/app/models.py`.

```sh
cd backend
uv run alembic upgrade head                              # apply
uv run alembic revision --autogenerate -m "describe it"  # create after changing models
uv run alembic check                                     # models and migrations are in sync
```

## Tests

```sh
docker compose up -d db
cd backend
uv run pytest
```

- `test_editor.py`: weights and the draft/publish state machine, pure functions, including the end-to-end
  example `34/33/33 → Add → 25×4 → Pin 40 → 40/20/20/20 → Remove → 40/0/30/30 → Bring back → 40/20/20/20 → Cancel → 34/33/33`.
- `test_api.py`, `test_creator.py`: HTTP endpoints against a real Postgres database `kcm_test`
  (created automatically) and an in-memory fake Keitaro. Includes creator rollback and the payloads sent to Keitaro.
- `test_keitaro.py`: the HTTP client (auth headers, error mapping) with `respx`.

## Configuration

All settings come from environment variables or the repo-root `.env` (see `.env.example`).

| Variable | Default | Meaning |
|---|---|---|
| `KEITARO_API_KEY` | (required) | Admin API key |
| `KEITARO_URL` | `https://tlgk.host/admin_api/v1` | Admin API base URL |
| `CAMPAIGN_PREFIX` | `test_kochkurov_` | Only campaigns with this prefix can be created, opened and edited |
| `DEFAULT_GROUP`, `DEFAULT_TRAFFIC_SOURCE` | `FORTESTS` | Preselected in the creator form |
| `DATABASE_URL` | local compose Postgres | SQLAlchemy async URL |

## How it works

Every offer in a stream is stored with two layers: **published** (what Keitaro has) and **draft**
(what the user sees). A stream is yellow when any row's draft differs from its published layer.

- Weights: pinned offers keep their pin, the other active offers split the rest evenly in whole percent
  (largest remainder: 34/33/33, never 33/33/33). Removed offers get 0 but keep their pin for Bring back.
- Push sends the full list of active offers in one `PUT /streams/{id}` (Keitaro replaces the whole list)
  and is blocked unless active shares sum to 100: Keitaro itself does not check it.
- Fetch refreshes the published layer. An offer deleted directly in Keitaro turns grey (removed) here
  instead of disappearing; weights from Keitaro are taken as is.

Code map: `app/editor.py` (all business rules, no I/O) · `app/creator.py` · `app/api.py` (endpoints) ·
`app/keitaro.py` (client) · `web/src/StreamCard.tsx` (editor UI).

## Safety

The Keitaro instance is shared production, so the app only ever writes to campaigns named
`CAMPAIGN_PREFIX*`: other campaigns are hidden, and fetching one is refused before its streams are read.
If creating a stream fails, the half-created campaign is deleted. Nothing calls Keitaro's archive cleanup.

## API

| Method | Path | Action |
|---|---|---|
| GET | `/api/meta` | Domains, groups, traffic sources and defaults for the creator |
| GET | `/api/offers?q=` | Offer autocomplete (active offers, by id or name) |
| GET | `/api/campaigns` | Our campaigns in Keitaro |
| POST | `/api/campaigns` | Create campaign with two streams |
| GET | `/api/campaigns/{id}` | Campaign from the local database |
| POST | `/api/campaigns/{id}/fetch` | Fetch streams from Keitaro and sync |
| POST | `/api/streams/{id}/offers` | Add offer |
| DELETE | `/api/streams/{id}/offers/{offer_id}` | Remove offer |
| POST | `/api/streams/{id}/offers/{offer_id}/restore` | Bring back |
| PUT / DELETE | `/api/streams/{id}/offers/{offer_id}/pin` | Pin at a share / unpin |
| POST | `/api/streams/{id}/push` | Publish the draft to Keitaro |
| POST | `/api/streams/{id}/cancel` | Discard the draft |

Interactive docs: http://localhost:8000/docs when running without Docker.
