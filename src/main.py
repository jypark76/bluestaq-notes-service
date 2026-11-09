import logging
import os

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.errors import InvalidInputError, MissingIdentityError, NotFoundError
from src.routes.notes import router as notes_router
from src.services.notes import NoteService
from src.store.notes import NoteStore


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    """Every error leaves the service in this one shape."""
    return JSONResponse(
        status_code=status_code, content={"error": {"code": code, "message": message}}
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

    @app.exception_handler(MissingIdentityError)
    def missing_identity(_: Request, exc: MissingIdentityError):
        return _error(status.HTTP_400_BAD_REQUEST, "missing_header", str(exc))

    @app.exception_handler(NotFoundError)
    def not_found(_: Request, exc: NotFoundError):
        return _error(status.HTTP_404_NOT_FOUND, "not_found", "note not found")

    @app.exception_handler(InvalidInputError)
    def invalid_input(_: Request, exc: InvalidInputError):
        return _error(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_input", str(exc))

    @app.exception_handler(Exception)
    def unexpected(_: Request, exc: Exception):
        # A bug on our side. The caller still gets the same error shape,
        # and the details stay in the server log instead of the response.
        logging.getLogger("uvicorn.error").exception("unhandled error", exc_info=exc)
        return _error(
            status.HTTP_500_INTERNAL_SERVER_ERROR, "internal_error", "unexpected error"
        )

    @app.exception_handler(StarletteHTTPException)
    def http_problem(_: Request, exc: StarletteHTTPException):
        # Unknown URL (404), wrong method (405) and similar. Without this
        # they would come back in FastAPI's own {"detail": ...} shape.
        code = {404: "not_found", 405: "method_not_allowed"}.get(
            exc.status_code, "http_error"
        )
        return _error(exc.status_code, code, str(exc.detail))

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
