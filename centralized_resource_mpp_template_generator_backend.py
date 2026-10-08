"""
Backward-compatibility bridge for centralized_resource_mpp_template_generator_backend.py.
Forwards directly to the modularized backend package in backend.app.main.
"""

from backend.app.main import app
from backend.app.services.xml_generator import build_ms_project_xml
from backend.app.api.routes import CALENDARS_DB, RESOURCES_DB

__all__ = ["app", "build_ms_project_xml", "CALENDARS_DB", "RESOURCES_DB"]


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("centralized_resource_mpp_template_generator_backend:app", host="127.0.0.1", port=8000, reload=True)