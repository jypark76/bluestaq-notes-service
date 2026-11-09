# Notes Service

A small REST API where several teams keep their own notes. Each team sees only its own. Built with FastAPI and SQLite.

## Run it

Needs Python 3.12 or newer.

    python -m venv .venv
    source .venv/bin/activate        # on Windows: .venv\Scripts\activate
    pip install -r requirements.txt
    uvicorn --factory src.main:create_app    # http://localhost:8000

Try it at http://localhost:8000/docs (fill in the two header fields), or with curl:

    curl -X POST localhost:8000/notes \
      -H "X-Team-Id: team-a" -H "X-User-Id: user-1" \
      -H "Content-Type: application/json" \
      -d '{"title": "Plan", "body": "Ship it", "tags": ["work"]}'

The database is a SQLite file, `notes.db`, created on first run. Set `NOTES_DB_PATH` to move it.

## Test it

    pytest
    ruff check . && ruff format --check .    # lint and format

## What I built

Every `/notes` call needs `X-Team-Id` (whose notes) and `X-User-Id` (the author). A missing or blank header returns 400.

| Endpoint | What it does |
|---|---|
| `POST /notes` | Create a note (201): `title`, `body`, optional `tags`. |
| `GET /notes` | List newest edit first. Query: `q`, `tag`, `limit` (1 to 100, default 20), `offset` (0 to 1,000,000). Returns `{items, total}`. |
| `GET /notes/{id}` | Fetch one note. |
| `PATCH /notes/{id}` | Change any of `title`, `body`, `tags`. |
| `DELETE /notes/{id}` | Delete a note (204). |
| `GET /health` | Liveness check, no headers. |

Limits: title 200 characters, body 10,000, tags 30 each and 20 per note (trimmed, lowercased, de-duplicated). `q` matches title or body in any letter case, `tag` matches one exact tag, and `total` counts every match.

Every error has one shape: `{"error": {"code": "not_found", "message": "note not found"}}`. The codes are `missing_header` (400), `not_found` (404), `method_not_allowed` (405, with an `Allow` header), `invalid_input` (422, naming the field) and `http_error` for any other framework error. A 500 (`internal_error`) means a bug on my side, and the details stay in the server log.

## Assumptions

- No real login: the headers stand in for it, so anyone who sets one is trusted. Fine here, unsafe for production.
- Everyone on a team can see, edit and delete all of its notes. The author is recorded but limits nothing.
- Times are UTC in ISO 8601, ids are opaque strings, and a blank `q` or `tag` means "no filter".

## Trade-offs

The three choices I spent the most time on:

**1. Team isolation lives in one place, and another team's note looks missing.**
Every store method takes a `team_id` and includes it in the SQL `WHERE` that finds the note, so search, tag filters and updates can't reach another team's notes. Another team's note returns the same 404 as a missing one, because a 403 would confirm the id is real. The cost: a mistyped id and a wrong team look alike when debugging.

**2. Three layers, with SQLite behind a small store class.**
Routes translate HTTP, the service holds the rules, and `NoteStore` holds all the SQL. I could test the rules with no web server, and moving to Postgres means rewriting one class. The cost: more files than one module. SQLite allows one writer at a time, so the store shares one connection behind a lock. That is fine here and the first thing to replace under heavy writes.

**3. Plain `LIKE` search and `limit`/`offset` paging.**
No extra dependency, easy to read, enough at team scale. `%`, `_` and `\` in a search are escaped. The limits: `LIKE` ignores case only for plain English letters (`ünï` won't match `ÜNÏ`), a search scans the team's notes, and offset paging can skip or repeat a note if notes change between pages.

## What I cut (3-hour time box)

Real authentication and team membership, per-note sharing, full-text search, migrations, Docker and CI, rate limiting and request logging.

## What I would do next

- **Add:** real authentication with a team membership table. FTS5 search. Migrations, and Postgres if more than one server must write. An edit check on `PATCH` that rejects a stale update.
- **Change:** give reads their own connections (SQLite WAL mode) so a write no longer makes every read wait behind the one lock.
- **Stop:** offset paging. Switch to keyset paging (continue from the last note seen) so pages stay stable.

## AI usage

Built with Claude Code, which the prompt allows. I chose the scope and approved each step before the next was built. The tests were written alongside the code and all pass.
