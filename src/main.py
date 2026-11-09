from fastapi import FastAPI


def create_app() -> FastAPI:
    """Build the web app. Tests call this to get a fresh copy each time."""
    app = FastAPI(title="Notes Service")

    @app.get("/health")
    def health():
        # A simple "are you alive?" check. It does not touch the database.
        return {"status": "ok"}

    return app


# This is the object the server starts: uvicorn src.main:app
app = create_app()
