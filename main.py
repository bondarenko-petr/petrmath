"""Website and REST API for trial lesson requests."""
import os
import sqlite3
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr, Field, field_validator

app = FastAPI(title="Круг Пи — математика, ОГЭ и ЕГЭ")
ROOT = Path(__file__).resolve().parent
DATABASE = Path(os.environ.get("TRIAL_REQUESTS_DB", str(ROOT / "data" / "trial_requests.sqlite3")))


class TrialRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    email: EmailStr = Field(max_length=254)
    phone: str = Field(default="", max_length=40)
    message: str = Field(default="", max_length=2000)
    courses: list[Literal["Математика", "ЕГЭ", "ОГЭ"]] = Field(min_length=1, max_length=3)
    consent: Literal[True]

    @field_validator("name", "phone", "message", mode="before")
    @classmethod
    def strip_text(cls, value):
        return value.strip() if isinstance(value, str) else value


@app.get("/api/health", tags=["System"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/trial-requests", status_code=201, tags=["Trial lessons"])
def create_trial_request(request: TrialRequest) -> dict[str, str]:
    try:
        DATABASE.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(DATABASE, timeout=10) as connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS trial_requests (
                id INTEGER PRIMARY KEY, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                name TEXT NOT NULL, email TEXT NOT NULL, phone TEXT NOT NULL,
                courses TEXT NOT NULL, message TEXT NOT NULL, consent INTEGER NOT NULL
            )""")
            connection.execute(
                "INSERT INTO trial_requests (name,email,phone,courses,message,consent) VALUES (?,?,?,?,?,?)",
                (request.name, str(request.email), request.phone,
                 ", ".join(dict.fromkeys(request.courses)), request.message, 1),
            )
    except (OSError, sqlite3.Error) as error:
        raise HTTPException(status_code=503, detail="Не удалось сохранить заявку") from error
    return {"status": "saved"}


# Database files stay outside the public static directory.
app.mount("/", StaticFiles(directory=str(ROOT / "landing" / "dist"), html=True), name="landing")
