# Antigravity Agent Guidelines: Centralized Project & Resource Hub

This document contains mandatory behavioral instructions, architecture standards, and design requirements for the **Antigravity agent** building and maintaining the **MS Project Centralized Resource & Template Hub**.

---

## 1. Executive Mission & Problem Domain

The organization requires a single web-based source of truth to eliminate MS Project Desktop synchronization issues:
1. **Identical Resource Directory:** Resources originated from Active Directory / Entra ID must have unified identities across all local `.mpp` files.
2. **Multiple Cost Rates:** Every resource must support multi-tier cost profiles (MS Project Cost Rate Tables `A`, `B`, `C`, `D`, `E`).
3. **Calendar Unification:** Base calendars and portal-originated absence/vacation dates must be uniformly applied.
4. **Custom Enterprise Metadata:** Custom fields missing in vanilla MS Project Desktop must be injected at template creation time.
5. **Instant Portability:** The web application exports a ready-to-use template (`.xml` or converted `.mpp`) with zero manual setup required by Project Managers.

---

## 2. Core Agent Principles

When extending or maintaining this product, the Antigravity agent **must strictly follow** these directives:

* **Principle of Non-Destructive Interoperability:** Never generate non-standard XML tags. Always adhere to the Microsoft Project XML Schema Specification (`http://schemas.microsoft.com/project`).
* **Zero Disconnected Data:** Every exported resource must belong to an official base calendar and have at least Rate Table `A` defined.
* **Separation of Concerns:**
  * **Web Application:** Handles permissions, AD sync, HR holiday imports, rate management, and export generation.
  * **MS Project Desktop:** Used purely for task breakdown, scheduling, dependency links, and Gantt tracking.
* **Resilience in Production:** Never rely on a locally installed MS Project executable on server runtimes. File generation must occur via server-native methods (native MSPDI XML serialization conforming to the Microsoft Project XML Schema; MPXJ is used for server-side parsing/reading of .mpp and .xml files).

---

## 3. Architecture & Functional Specifications

### 3.1. Resource & Cost Rates Module
* Active Directory objects (UPN, Name, Email, Department) form the core identity.
* Each resource must expose 5 distinct rate tables:
  * **Table A (Index 0):** Standard internal company rate.
  * **Table B (Index 1):** Overtime / Special shifts.
  * **Table C (Index 2):** Customer-billable rate or consulting rate.
  * **Table D (Index 3):** Subcontractor rate.
  * **Table E (Index 4):** Reserved / Emergency rate.
* Antigravity must ensure that rate tables are converted to integers `0` through `4` inside the `<RateTable>` XML element.

### 3.2. Calendars & Holiday Management
* Must support Base Calendars (e.g., 5-day / 40-hour work week) and exceptions.
* Exceptions must include start and end dates with `DayWorking = 0` (holidays/vacations) or `DayWorking = 1` (custom working shifts).
* All dates in exported files must use ISO-8601 formatted timestamps (e.g., `YYYY-MM-DDTHH:MM:SS`).

### 3.3. Custom Field Configuration (Extended Attributes)
* Vanishing or non-standard desktop fields must be populated through `<ExtendedAttributes>`.
* Common enterprise IDs:
  * `Text1` through `Text30` (Field IDs `188743731`, etc.)
  * `Cost1` through `Cost10`
  * `Flag1` through `Flag20`
* The agent must allow mapping human-readable names (e.g., "Contract Type", "Cost Center") as `Alias` tags.

---

## 4. Technical Constraints for the Agent

| Component | Standard / Constraint |
| :--- | :--- |
| **Backend Framework** | FastAPI (Python 3.11+) or Node.js / TypeScript. |
| **Export Format** | Native MS Project XML Schema (`.xml`). For reading and ingesting existing `.mpp`/`.xml` files, use `MPXJ` (note: MPXJ is read-only for `.mpp`). |
| **Date Time Format** | Strict ISO 8601 (`YYYY-MM-DDTHH:MM:SS`). |
| **Authentication** | Entra ID / OAuth 2.0 (MSAL) for Microsoft Graph API integration. |
| **Database** | Relational DB (PostgreSQL / SQLite for development) with ACID transactions for rate history. |

---

## 5. Agent Verification Checklist

Before validating any PR or feature delivery, the agent must verify:
- [ ] The generated `.xml` template opens directly in **MS Project Desktop** (2016, 2019, 2021, and Microsoft 365 Apps) without schema warnings.
- [ ] Task `0` (Project Summary Task) exists and correctly aggregates project metadata.
- [ ] Opening **Resource Sheet** shows exact AD names, emails, and default standard rates.
- [ ] Opening **Resource Information -> Costs** reveals configured rates in tabs `A`, `B`, and `C`.
- [ ] Project-level calendar shows imported exceptions and holidays in **Change Working Time**.
- [ ] Custom fields are visible under column selection.