"""Website and REST API for trial lesson requests."""
import sqlite3
import mysql.connector
from database import save_request
from accounts import router as accounts_router
from admin import router as admin_router
from lessons import router as lessons_router
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr, Field, field_validator

app = FastAPI(title="Круг Пи — математика, ОГЭ и ЕГЭ")
ROOT = Path(__file__).resolve().parent


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
        save_request(request)
    except (OSError, sqlite3.Error, mysql.connector.Error, ValueError) as error:
        raise HTTPException(status_code=503, detail="Не удалось сохранить заявку") from error
    return {"status": "saved"}


app.include_router(accounts_router)
app.include_router(admin_router)
app.include_router(lessons_router)


@app.exception_handler(sqlite3.Error)
@app.exception_handler(mysql.connector.Error)
async def mysql_failure(request, error):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=503, content={"detail": "База временно недоступна"})


# Database files stay outside the public static directory.
app.mount("/", StaticFiles(directory=str(ROOT / "landing" / "dist"), html=True), name="landing")
