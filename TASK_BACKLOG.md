# TASK BACKLOG

## In Progress
*(Leave empty or put currently assigned task here)*

## Planned (Backlog)
- [ ] [SEC-3] Tighten project ownership authorization (`_is_project_owner`), Graph OData/UUID input validation, and DOM-XSS / CSP hardening in `index.html`.
- [ ] [TEST] Expand automated pytest coverage for MSPDI XML schema validation.
- [ ] [FEAT] Implement audit logging for resource rate modifications.
- [ ] [UI] Improve user experience for calendar exception imports.




## Completed
- [x] Initial project scaffolding and directory structure setup.
- [x] Hyper-V deployment script and Ubuntu 24.04 provisioning configuration.
- [x] Entra ID SSO integration and emergency admin authentication gate.
- [x] Dual compose setup (`docker-compose.yml` for Postgres, `docker-compose.sqlite.yml` for dev).
- [x] Core resource rate tables (A–E) and base calendar XML export pipeline.
- [x] Fix MS Project XML calendar export: omit BaseCalendarUID on base calendars, enforce 51-char limit, sort project calendar first, and output UTF-8 XML declaration so calendars appear in MS Project Desktop calendar menu.
- [x] Refactor project list: move export (.XML), upload, refresh, and close/reopen buttons to a dedicated terminal Actions column.
- [x] Project owner selection from portal users in project template creation & Admin project ownership transfer endpoint and modal UI.
- [x] Align Baseline Cost, Budget Cost, and Baseline Budget Cost parsing and snapshot calculation with Microsoft Project logic during schedule upload action.
- [x] Microsoft SQL Server migration engine, dialect abstraction (pyodbc/pymssql), container compose (`docker-compose.mssql.yml`), and automated data transfer utility (`backend/app/scripts/migrate_to_mssql.py`).
- [x] Fix character encoding mojibake for Baltic and international text: enforce native NVARCHAR Unicode columns on Microsoft SQL Server and add defensive Baltic mojibake restoration utility.
- [x] Add option to remove calendar from calendar list for Administrator role users (`DELETE /api/calendars/{calendar_id}`) with cascade cleanup, assignment guards, and audit trail.
- [x] Add function to import new project from MPP file (`POST /api/projects/import-mpp`), requiring Project Manager assignment from registered portal users and naming project from top task description.
- [x] Fix MPP binary file import: repair inverted JVM initialization logic in MPXJ parser and implement multi-stage JVM runtime auto-discovery (settings, JAVA_HOME, common Windows JDK/JBR paths, JPype default) with Windows signal suppression.
- [x] Comprehensive cybersecurity architecture & codebase audit with prioritized hardening recommendations.
- [x] [SEC-1] Harden Entra SSO code exchange (`id_token` audience/tenant verification, OAuth2 CSRF `state` & PKCE `code_verifier` support) and spoof-resistant IP/account rate limiting.
- [x] [SEC-2] Run Docker container as non-root `mppuser` (`Dockerfile`), enforce `no-new-privileges:true` in Compose, and disable runtime `.env` overwrite in production (`POST /api/entra/config`).