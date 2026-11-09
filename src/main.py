import os

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

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

    @app.exception_handler(RequestValidationError)
    def bad_shape(_: Request, exc: RequestValidationError):
        # The request was the wrong shape (missing field, wrong type, bad JSON).
        first = exc.errors()[0]
        where = ".".join(str(part) for part in first["loc"] if part != "body")
        message = f"{where}: {first['msg']}" if where else first["msg"]
        return _error(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_input", message)

    return app
