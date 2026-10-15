```markdown
# SYSTEM STATE & ARCHITECTURE DIRECTORY

**Project Name:** MS Project Centralized Resource & Template Hub (`mpp-web-portal`)  
**Target Environments:** Ubuntu Server 24.04 LTS (Hyper-V VM) & Local Development

---

## 1. Technology Stack
- **Backend Framework:** FastAPI >= 0.110.0 (Python 3.11+, Uvicorn, Pydantic v2)
- **Database & ORM:** SQLAlchemy 2.0+, Alembic (Multi-engine: Microsoft SQL Server 2022 / PostgreSQL 16 / SQLite for local testing)
- **Database Drivers:** `pyodbc` (ODBC Driver 17/18 for SQL Server), `pymssql` (pure-Python FreeTDS), `psycopg2` / `psycopg3` (PostgreSQL), `sqlite3`
- **Project File Processing:** MPXJ >= 16.10.0 + JPype1 (read/parse `.mpp`/`.xml`), Native MSPDI XML serializer (export `.xml`)
- **Authentication & Directory Sync:** Microsoft Entra ID (MSAL, Microsoft Graph API, PyJWT) + Emergency Local Admin
- **Containerization:** Docker Engine, Docker Compose v2 (Multi-profile: `docker-compose.yml` for Postgres, `docker-compose.mssql.yml` for MS SQL Server, `docker-compose.sqlite.yml` for dev)
- **Web Server / Reverse Proxy:** NGINX with 50MB upload buffer for project files

---

## 2. Core Functional Modules
1. **Resource Directory & Entra ID Sync:**
   - Fetches users/identities from Entra ID (UPN, Name, Email, Department).
   - Manages unified resource identities across project schedules.
2. **Multi-Tier Cost Rate Tables:**
   - Stores and serializes 5 distinct rate tables per resource:
     - Table A (0): Standard internal rate.
     - Table B (1): Overtime / Special shifts.
     - Table C (2): Customer-billable / Consulting rate.
     - Table D (3): Subcontractor rate.
     - Table E (4): Emergency / Reserved rate.
3. **Calendar & Working Time Engine:**
   - Base 5-day / 40-hour work week calendars.
   - Holiday and vacation exceptions (`DayWorking=0` / `DayWorking=1`) using `holidays` library.
   - Admin calendar management: creation, weekly shift updates, renaming, hiding/unhiding, and permanent deletion (`DELETE /api/calendars/{calendar_id}`) with resource/project assignment guards and cascade cleanup.
4. **Template Export & Schema Generator:**
   - Generates compliant MS Project XML templates containing injected resources, cost tables, extended attributes (`Text1-Text30`, `Cost1-Cost10`, `Flag1-Flag20`), and base calendars.
5. **Authentication Gate & Portfolio Governance:**
   - Mandatory login gate via Microsoft Entra ID SSO.
   - Emergency fallback admin user (`emergency_admin`).
   - Project template creation selects project owner exclusively from active portal users.
   - Admin-exclusive project ownership transfer (`PUT /api/projects/{id}/transfer`) with audit trail.
6. **Schedule Upload & Baseline/Budget Cost Engine (MS Project Compliant):**
   - Adheres to Microsoft Project logic: Task 0 Budget Resource assignments define `Budget Cost` and `Baseline Budget Cost`.
   - Work baseline costs roll up from leaf tasks when summary baseline cost is omitted or zero.
   - Harmonizes project master budget (`ProjectDB.budget_cost`) and snapshot metrics upon schedule upload.
7. **Microsoft SQL Server Engine & Migration Automation:**
   - Dialect-aware connection pooling and engine initialization (`configure_engine`) supporting `mssql+pyodbc` (with `fast_executemany`) and `mssql+pymssql`.
   - Zero-data-loss CLI migration script (`backend/app/scripts/migrate_to_mssql.py`) with topological foreign-key batching and `SET IDENTITY_INSERT` handling.
   - Containerized MS SQL Server 2022 deployment via `docker-compose.mssql.yml`.
8. **Unicode Character Integrity & Mojibake Prevention:**
   - Enforces `NVARCHAR` Unicode column compilation for MS SQL Server across all SQLAlchemy text definitions (`backend/app/db/session.py`).
   - Dynamic schema alignment (`_ensure_mssql_unicode`) to convert existing single-byte `VARCHAR` columns to `NVARCHAR` while preserving indexes and nullability.
   - Restores Baltic special characters (`ą, č, ę, ė, į, š, ų, ū, ž`) across calendar exceptions, resources, projects, and user display names.


---

## 3. High-Risk / Protected Core Components (DO NOT BREAK)
- `backend/app/` XML generation logic conforming to `http://schemas.microsoft.com/project`.
- Alembic database schema migrations (`alembic/versions/`).
- Hyper-V VM deployment automation (`deploy/Create-HyperV-LinuxVM.ps1` and `deploy/ubuntu-vm-install.sh`).
- Container service definitions in `docker-compose.yml`.