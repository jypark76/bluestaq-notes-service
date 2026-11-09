import os

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.routing import Match

from src.errors import (
    InvalidIdentityError,
    InvalidInputError,
    MissingIdentityError,
    NotFoundError,
)
from src.routes.notes import router as notes_router
from src.services.notes import NoteService
from src.store.notes import NoteStore

# A note at every limit (200-character title, 10,000-character body, 20 tags)
# is well under 100 KB, even when every character needs a multi-byte escape.
MAX_REQUEST_BYTES = 100_000


def _error(
    status_code: int, code: str, message: str, headers: dict[str, str] | None = None
) -> JSONResponse:
    """Every error leaves the service in this one shape."""
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
        headers=headers,
    )


def create_app(db_path: str | None = None) -> FastAPI:
    """Build the web app.

    db_path is where the SQLite file lives. If not given, we use the
    NOTES_DB_PATH environment variable, then fall back to "notes.db".
    Tests pass ":memory:" to get a throwaway database.
    """
    db_path = db_path or os.environ.get("NOTES_DB_PATH", "notes.db")

    app = FastAPI(title="Notes Service")
    app.state.service = NoteService(NoteStore(db_path))
    app.include_router(notes_router)

    @app.get("/health")
    def health():
        # A simple "are you alive?" check. It needs no headers and no database.
        return {"status": "ok"}

    @app.middleware("http")
    async def limit_body_size(request: Request, call_next):
        # Refuse a huge upload before it is read. This checks the declared
        # Content-Length only, so a client that streams without one is not caught.
        declared = request.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > MAX_REQUEST_BYTES:
            return _error(
                status.HTTP_413_CONTENT_TOO_LARGE,
                "payload_too_large",
                f"request body must be {MAX_REQUEST_BYTES} bytes or fewer",
            )
        return await call_next(request)

    @app.exception_handler(MissingIdentityError)
    def missing_identity(_: Request, exc: MissingIdentityError):
        return _error(status.HTTP_400_BAD_REQUEST, "missing_header", str(exc))

    @app.exception_handler(InvalidIdentityError)
    def invalid_identity(_: Request, exc: InvalidIdentityError):
        return _error(status.HTTP_400_BAD_REQUEST, "invalid_header", str(exc))

    @app.exception_handler(NotFoundError)
    def not_found(_: Request, exc: NotFoundError):
        return _error(status.HTTP_404_NOT_FOUND, "not_found", "note not found")

    @app.exception_handler(InvalidInputError)
    def invalid_input(_: Request, exc: InvalidInputError):
        return _error(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_input", str(exc))

    @app.exception_handler(Exception)
    def unexpected(_: Request, exc: Exception):
        # A bug on our side. The caller still gets the same error shape.
        # The server logs the full traceback itself after this response goes
        # out, so we do not log it here too (that printed every error twice).
        return _error(
            status.HTTP_500_INTERNAL_SERVER_ERROR, "internal_error", "unexpected error"
        )

    @app.exception_handler(StarletteHTTPException)
    def http_problem(request: Request, exc: StarletteHTTPException):
        # Unknown URL (404), wrong method (405) and similar. Without this
        # they would come back in FastAPI's own {"detail": ...} shape.
        if exc.status_code == 400:
            # The framework could not read the body at all (for example bytes
            # that are not valid UTF-8). Treat it like any other bad input.
            return _error(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "invalid_input",
                "body: could not be read",
            )
        code = {404: "not_found", 405: "method_not_allowed"}.get(
            exc.status_code, "http_error"
        )
        headers = dict(exc.headers or {})
        if exc.status_code == 405:
            # The framework lists only one route's methods. A 405 must name
            # every method this path accepts, so try each one against the routes.
            allowed = [
                method
                for method in ("GET", "POST", "PUT", "PATCH", "DELETE")
                if any(
                    route.matches({**request.scope, "method": method})[0] == Match.FULL
                    for route in request.app.routes
                )
            ]
            headers["Allow"] = ", ".join(allowed)
        return _error(exc.status_code, code, str(exc.detail), headers)

    @app.exception_handler(RequestValidationError)
    def bad_shape(_: Request, exc: RequestValidationError):
        # The request was the wrong shape (missing field, wrong type, bad JSON).
        # Name the field, and say "body" when the whole body is the problem.
        first = exc.errors()[0]
        names = [str(p) for p in first["loc"] if p != "body" and not isinstance(p, int)]
        where = ".".join(names) or "body"
        return _error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "invalid_input",
            f"{where}: {first['msg']}",
        )

    return app
