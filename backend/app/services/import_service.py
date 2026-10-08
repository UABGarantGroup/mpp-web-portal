"""
CSV and Excel import service with row-level validation previews for Resources and Cost Rates.
"""

from datetime import date, datetime
import io
from typing import Any, Dict, List, Optional, Tuple
import pandas as pd
from sqlalchemy.orm import Session

from backend.app.db.models import CustomFieldDB, RatePeriodDB, ResourceDB, ResourceFieldValueDB
from backend.app.models.enums import RateTableEnum, ResourceKindEnum, ResourceTypeEnum


def parse_dataframe_from_bytes(content: bytes, filename: str) -> pd.DataFrame:
    """
    Parses uploaded file bytes (CSV or XLSX) into a pandas DataFrame.
    """
    if filename.lower().endswith(".csv"):
        # Try UTF-8 then Latin-1 for Baltic characters
        try:
            return pd.read_csv(io.BytesIO(content), encoding="utf-8")
        except UnicodeDecodeError:
            return pd.read_csv(io.BytesIO(content), encoding="latin-1")
    elif filename.lower().endswith((".xlsx", ".xls")):
        return pd.read_excel(io.BytesIO(content))
    else:
        raise ValueError("Unsupported file format. Please upload .csv or .xlsx")


def validate_and_import_resources(
    db: Session,
    content: bytes,
    filename: str,
    dry_run: bool = True
) -> Dict[str, Any]:
    """
    Validates resource rows from CSV/Excel and optionally commits them to the database.
    """
    df = parse_dataframe_from_bytes(content, filename)
    df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]

    valid_rows = []
    errors = []

    for index, row in df.iterrows():
        row_num = index + 2  # Excel row numbering (1-indexed + header)
        name = str(row.get("name", "")).strip()
        if not name or name == "nan":
            errors.append({"row": row_num, "field": "name", "error": "Resource name is required"})
            continue

        email = str(row.get("email", "")).strip()
        if email == "nan": email = None

        department = str(row.get("department", "")).strip()
        if department == "nan": department = None

        raw_type = str(row.get("resource_type", "Work")).strip().capitalize()
        try:
            res_type = ResourceTypeEnum(raw_type)
        except ValueError:
            res_type = ResourceTypeEnum.WORK

        raw_kind = str(row.get("resource_kind", "Named")).strip().capitalize()
        try:
            res_kind = ResourceKindEnum(raw_kind)
        except ValueError:
            res_kind = ResourceKindEnum.NAMED

        is_generic = res_kind == ResourceKindEnum.GENERIC or str(row.get("is_generic", "")).strip().lower() in ("true", "1", "yes")

        valid_rows.append({
            "name": name,
            "email": email,
            "department": department,
            "resource_type": res_type,
            "resource_kind": res_kind,
            "is_generic": is_generic,
            "base_calendar_id": int(row.get("calendar_id", 1)) if pd.notna(row.get("calendar_id")) else 1,
        })

    if not dry_run and not errors:
        for r_data in valid_rows:
            # Check if exists by email or name
            existing = None
            if r_data["email"]:
                existing = db.query(ResourceDB).filter(ResourceDB.email == r_data["email"]).first()
            if not existing:
                existing = db.query(ResourceDB).filter(ResourceDB.name == r_data["name"]).first()

            if existing:
                existing.department = r_data["department"]
                existing.is_active = True
            else:
                new_res = ResourceDB(**r_data)
                db.add(new_res)
        db.commit()

    return {
        "total_rows": len(df),
        "valid_count": len(valid_rows),
        "error_count": len(errors),
        "errors": errors,
        "preview": valid_rows[:10],
        "committed": not dry_run and len(errors) == 0,
    }


def validate_and_import_rates(
    db: Session,
    content: bytes,
    filename: str,
    created_by: str,
    dry_run: bool = True
) -> Dict[str, Any]:
    """
    Validates and imports rate table entries (A-E) for resources.
    """
    df = parse_dataframe_from_bytes(content, filename)
    df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]

    valid_rates = []
    errors = []

    for index, row in df.iterrows():
        row_num = index + 2
        # Lookup resource by identifier
        res_id = row.get("resource_id")
        email = str(row.get("email", "")).strip()
        name = str(row.get("name", "")).strip()

        resource = None
        if pd.notna(res_id):
            resource = db.query(ResourceDB).filter(ResourceDB.id == int(res_id)).first()
        elif email and email != "nan":
            resource = db.query(ResourceDB).filter(ResourceDB.email == email).first()
        elif name and name != "nan":
            resource = db.query(ResourceDB).filter(ResourceDB.name == name).first()

        if not resource:
            errors.append({"row": row_num, "field": "resource", "error": f"Resource not found (ID: {res_id}, Email: {email}, Name: {name})"})
            continue

        raw_table = str(row.get("rate_table", "A")).strip().upper()
        if raw_table not in ("A", "B", "C", "D", "E"):
            errors.append({"row": row_num, "field": "rate_table", "error": f"Invalid rate table '{raw_table}'. Must be A, B, C, D, or E."})
            continue

        try:
            std_rate = float(row.get("standard_rate", 0.0))
            if std_rate < 0:
                raise ValueError()
        except (ValueError, TypeError):
            errors.append({"row": row_num, "field": "standard_rate", "error": "Standard rate must be a non-negative number."})
            continue

        try:
            ot_rate = float(row.get("overtime_rate", 0.0)) if pd.notna(row.get("overtime_rate")) else 0.0
            cost_per_use = float(row.get("cost_per_use", 0.0)) if pd.notna(row.get("cost_per_use")) else 0.0
        except (ValueError, TypeError):
            ot_rate, cost_per_use = 0.0, 0.0

        raw_date = row.get("effective_date")
        eff_date = None
        if pd.notna(raw_date):
            if isinstance(raw_date, (datetime, date)):
                eff_date = raw_date if isinstance(raw_date, date) else raw_date.date()
            else:
                try:
                    eff_date = datetime.strptime(str(raw_date).strip(), "%Y-%m-%d").date()
                except ValueError:
                    errors.append({"row": row_num, "field": "effective_date", "error": "Invalid date format. Expected YYYY-MM-DD."})
                    continue

        valid_rates.append({
            "resource_id": resource.id,
            "resource_name": resource.name,
            "rate_table": RateTableEnum(raw_table),
            "standard_rate": std_rate,
            "overtime_rate": ot_rate,
            "cost_per_use": cost_per_use,
            "effective_date": eff_date,
            "created_by": created_by,
        })

    if not dry_run and not errors:
        for rate_data in valid_rates:
            res_id = rate_data.pop("resource_name")
            new_rate = RatePeriodDB(**rate_data)
            db.add(new_rate)
        db.commit()

    return {
        "total_rows": len(df),
        "valid_count": len(valid_rates),
        "error_count": len(errors),
        "errors": errors,
        "preview": valid_rates[:10],
        "committed": not dry_run and len(errors) == 0,
    }
