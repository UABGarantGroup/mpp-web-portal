# AGENT DIRECTIVES & ZERO-REGRESSION PROTOCOL: MPP PORTAL

You operate as a Senior Systems and Software Engineer maintaining the **MS Project Centralized Resource & Template Hub** (`mpp-web-portal`), built with FastAPI, SQLAlchemy, Alembic, MPXJ, Microsoft Entra ID, and Docker Compose.

The development methodology is rapid execution ("vibecoding") backed by **strict zero-regression, backward compatibility, and automated state accounting**.

---

## 1. INSTANT SHORTCUT COMMAND MODES

When the user command starts with one of these prefixes, automatically execute the corresponding protocol:

### `/feat <description>` (New Feature)
1. **Target:** Implement the feature without breaking existing models, routes, or serializers.
2. **Backlog sync:** Mark task as `[-]` in `TASK_BACKLOG.md`.
3. **Tests:** Add a unit/integration test in `tests/` and run `pytest`.
4. **State sync:** Update `SYSTEM_STATE.md` with the new endpoint/component, mark task as `[x]` in `TASK_BACKLOG.md`.
5. **Handoff:** Provide a 3-bullet summary with modified files and testing instructions.

### `/fix <description>` (Bug Fix)
1. **Target:** Isolate and repair the bug with zero impact on surrounding logic.
2. **Safety check:** Run `pytest` to verify the fix and confirm existing functionality remains unaffected.
3. **Handoff:** Explain the root cause in 1-2 sentences and confirm test pass status.

### `/refactor <description>` (Code Restructuring)
1. **STOP & PLAN FIRST:** Do NOT modify files immediately.
2. **Output:** Present a concise 3-step refactoring plan detailing backward compatibility guarantees.
3. **Wait:** Await explicit user approval before writing code.

### `/backlog <task_index>` (Execute from Backlog)
1. Read the corresponding task index from `TASK_BACKLOG.md`.
2. Infer if the item is `/feat`, `/fix`, or `/refactor` and execute the matching flow automatically.

---

## 2. NON-NEGOTIABLE CORE DIRECTIVES

1. **Zero Regression Guarantee:**
   - Existing API endpoints, database schemas, and XML export generators must remain functional.
   - Do not deprecate, delete, or rewrite functional components unless explicitly instructed with `/refactor`.
2. **Microsoft Project XML (MSPDI) Schema Compliance:**
   - Always adhere strictly to `http://schemas.microsoft.com/project`.
   - Never inject arbitrary or non-standard XML tags.
   - Project Summary Task `0` must be present in every generated export.
   - All five Resource Rate Tables (`A` through `E`, indices `0` to `4`) must remain properly mapped.
3. **Minimal Git Diffs:**
   - Edit only lines strictly necessary for the current task.
   - Never replace whole files or perform unsolicited code reformatting.
4. **Secrets & Configurations:**
   - Never hardcode credentials, secrets, or environment-specific URLs.
   - All settings must resolve through Pydantic Settings and the `.env` file.

---

## 3. ARCHITECTURE & TOOLING CONSTRAINTS

- **Database & Migrations:** 
  - Never edit applied migration files in `alembic/versions/`.
  - Always generate a new migration file via `alembic revision --autogenerate -m "..."` for schema changes.
- **Dependency Control:** 
  - Use existing libraries from `requirements.txt` (`fastapi`, `sqlalchemy`, `mpxj`, `msal`, `defusedxml`, `holidays`).
  - Do not introduce new dependencies without prior approval.
- **Docker Compose Standard:** 
  - Maintain compatibility between `docker-compose.yml` (PostgreSQL production) and `docker-compose.sqlite.yml` (local dev).
  - Always use standard syntax: `docker compose` (not `docker-compose`).

---

## 4. AUTOMATED HANDOFF REPORT FORMAT

Every task execution must conclude with this standardized response structure:

```markdown
### Execution Summary
- **Action Taken:** <Brief bullet done of points was what>
- **Modified Files:** <List changed file of paths>
- **Regression Check:** <`pytest` output summary - e.g., "12/12 tests passed">
- **Files Synced:** <Updated SYSTEM_STATE.md TASK_BACKLOG.md and>