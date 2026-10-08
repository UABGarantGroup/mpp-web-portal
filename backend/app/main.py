"""
Main FastAPI Application for MS Project Centralized Resource & Template Hub.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api.routes import router

app = FastAPI(
    title="MS Project Centralized Resource & Template Hub",
    description="Enterprise hub for Active Directory resources, multi-tier rate tables, national calendars, and MS Project XML template generation.",
    version="1.0.0",
)

# CORS Middleware configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Can be restricted in production config
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.app.main:app", host="127.0.0.1", port=8000, reload=True)
