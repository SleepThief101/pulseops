
from fastapi import FastAPI, HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from app.config import settings


# Database connection
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
)


# FastAPI application
app = FastAPI(
    title="PulseOps API",
    description="AI-native control tower for small SaaS teams.",
    version="0.1.0",
)


@app.get("/", tags=["General"])
def root():
    return {
        "message": "PulseOps API is running",
        "version": "0.1.0",
    }


@app.get("/health", tags=["Health"])
def health_check():
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))

        return {"status": "ok"}

    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail="Database unavailable",
        ) from exc
