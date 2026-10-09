"""
Main FastAPI Application for MS Project Centralized Resource & Template Hub.
Initializes database schema and default enterprise master data on startup.
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api.routes import router
from backend.app.core.config import settings
from backend.app.db.init_db import init_db
from backend.app.db.session import SessionLocal


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize DB and seeds
    db = SessionLocal()
    try:
        init_db(db)
    finally:
        db.close()

    # Pre-initialize MPXJ / Java runtime in headless mode
    try:
        from backend.app.services.mpxj_parser import _init_mpxj
        _init_mpxj()
    except Exception as e:
        print("MPXJ pre-initialization warning:", e)

    yield
    # Shutdown logic if needed


app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Enterprise hub for Active Directory resources, multi-tier rate tables, national calendars, and MS Project XML template generation.",
    version=settings.VERSION,
    lifespan=lifespan,
)

# CORS Middleware configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)

import os
from fastapi.staticfiles import StaticFiles

static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.app.main:app", host="127.0.0.1", port=8000, reload=True)
