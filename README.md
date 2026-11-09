# Notes Service

A small REST API where several teams keep their own notes. Each team sees only its own. Built with FastAPI and SQLite.

## Run it

Needs Python 3.12 or newer.

    python -m venv .venv
    source .venv/bin/activate        # on Windows: .venv\Scripts\activate
    pip install -r requirements.txt
    uvicorn --factory src.main:create_app    # http://localhost:8000

Try it in a browser at http://localhost:8000/docs (fill in the two header fields), or with curl:

    curl -X POST localhost:8000/notes \
      -H "X-Team-Id: team-a" -H "X-User-Id: user-1" \
      -H "Content-Type: application/json" \
      -d '{"title": "Plan", "body": "Ship it", "tags": ["work"]}'

The database is a SQLite file named `notes.db`, created on first run. Set `NOTES_DB_PATH` to move it.

## Test it

    pytest

Lint and format check:

    ruff check . && ruff format --check .

## What I built

Every `/notes` call needs two headers: `X-Team-Id` (whose notes) and `X-User-Id` (who is calling, saved as the author). A missing or blank header returns 400.

| Endpoint | What it does |
|---|---|
| `POST /notes` | Create a note (201). Body: `title`, `body`, optional `tags`. |
| `GET /notes` | List the team's notes, newest edit first. Query: `q` (search title and body), `tag`, `limit` (1 to 100, default 20), `offset` (0 to 1,000,000). Returns `{items, total}`. |
| `GET /notes/{id}` | Fetch one note. |
| `PATCH /notes/{id}` | Change any of `title`, `body`, `tags`. Fields you leave out stay as they are. |
| `DELETE /notes/{id}` | Delete a note (204). |
| `GET /health` | Liveness check. Needs no headers. |

- Title and body are trimmed and can't be empty. The title is at most 200 characters and the body 10,000.
- Tags are trimmed, lowercased and de-duplicated, at most 30 characters each and 20 per note.
- Text must be storable as UTF-8. `q` and `tag` can be combined with paging, and `total` counts every match.

Every error has one shape: `{"error": {"code": "not_found", "message": "note not found"}}`. The codes are `missing_header` (400), `not_found` (404, also for an unknown URL), `method_not_allowed` (405) and `invalid_input` (422, with the field named in the message). Any other framework error uses `http_error`. Bad input gets a 4xx, and a 405 lists the allowed methods in an `Allow` header. A 500 (`internal_error`) means a bug on my side, and its details stay in the server log.

## Assumptions

- There is no real login. The headers stand in for it, so anyone who sets one is trusted. Fine for this exercise, unsafe for production.
- Everyone on a team can see, edit and delete all of that team's notes. The author is recorded but limits nothing.
- Times are UTC in ISO 8601. Ids are opaque strings. A blank `q` or `tag` means "no filter".

## Trade-offs

The three choices I spent the most time on:

**1. Team isolation lives in one place, and another team's note looks missing.**
Every store method takes a `team_id` and puts it first in the SQL `WHERE`, so search and tag filters can't reach another team's notes. Another team's note returns the same 404 as a note that doesn't exist, because a 403 would confirm the id is real. The cost: a mistyped id and a wrong team look alike when debugging.

**2. Three layers, with SQLite behind a small store class.**
Routes translate HTTP, the service holds the rules, and `NoteStore` holds all the SQL. I could test the rules with no web server, and moving to Postgres means rewriting one class. Request models check only shape, so each limit is written once, in the service. The cost: more files than a single module. SQLite also allows one writer at a time, so the store shares one connection behind a lock. That is fine here and would be the first thing to replace under heavy writes.

**3. Plain `LIKE` search and `limit`/`offset` paging.**
No extra dependency, easy to read, enough at team scale. `%` and `_` in a search are escaped. The limits: SQLite's `LIKE` ignores case only for plain English letters (`ünï` won't match `ÜNÏ`), a search scans the team's notes, and offset paging can skip or repeat a note if notes change between pages.

## What I cut (3-hour time box)

Real authentication and team membership, per-note sharing, full-text search, migrations, Docker and CI, rate limiting and request logging.

## What I would do next

- **Add:** real authentication with a team membership table. FTS5 search. Migrations, and Postgres if more than one server must write. An edit check on `PATCH` that rejects a stale update.
- **Change:** load tags for a whole page in one query. Today the list endpoint runs one extra query per note.
- **Stop:** offset paging. Switch to keyset paging (continue from the last note seen) so pages stay stable.

## AI usage

Built with Claude Code, which the prompt allows. I chose the scope and approved each step before the next was built. The tests were written alongside the code and all pass.
