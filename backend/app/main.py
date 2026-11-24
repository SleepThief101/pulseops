from fastapi import FastAPI, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.db.session import engine
from app.routers import auth as auth_router
from app.routers.me import me_router

# FastAPI application
app = FastAPI(
    title="PulseOps API",
    description="AI-native control tower for small SaaS teams.",
    version="0.1.0",
)

# Routers
app.include_router(auth_router.router)
app.include_router(me_router)


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
