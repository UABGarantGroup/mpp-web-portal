# TASK BACKLOG

## In Progress
*(Leave empty or put currently assigned task here)*

## Planned (Backlog)
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