"""Local website and REST API application."""
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="Математика с пониманием")


@app.get("/api/health", tags=["System"])
def health() -> dict[str, str]:
    return {"status": "ok"}


landing_directory = Path(__file__).resolve().parent / "landing" / "dist"
# Register API routes before this catch-all static mount.
app.mount("/", StaticFiles(directory=str(landing_directory), html=True), name="landing")
