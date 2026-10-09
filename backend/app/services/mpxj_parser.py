"""
Service for reading, parsing, and extracting project metrics from Microsoft Project files (.mpp and .xml).
Uses MPXJ with fallback XML parsing.
"""

import os
import logging
from typing import Dict, Any, List, Optional
import xml.etree.ElementTree as ET
from datetime import datetime, date

logger = logging.getLogger(__name__)

# JVM and MPXJ initialization state
_jvm_initialized = False


def _init_mpxj():
    global _jvm_initialized
    if _jvm_initialized:
        return True

    try:
        import jpype
        if jpype.isJVMStarted():
            _jvm_initialized = True
            return True

        from backend.app.core.config import settings
        import mpxj

        mpxj_dir = os.path.join(os.path.dirname(mpxj.__file__), "lib")
        jars = [os.path.join(mpxj_dir, f) for f in os.listdir(mpxj_dir) if f.endswith(".jar")]

        jvm_path = settings.JVM_PATH
        if not os.path.exists(jvm_path):
            # Try default or JAVA_HOME
            java_home = os.environ.get("JAVA_HOME")
            if java_home:
                candidate = os.path.join(java_home, "bin", "server", "jvm.dll")
                if os.path.exists(candidate):
                    jvm_path = candidate

        if os.path.exists(jvm_path):
            # Ensure the directory containing awt.dll and dependent DLLs (e.g. jbr/bin) is on PATH
            jvm_bin_dir = os.path.abspath(os.path.join(os.path.dirname(jvm_path), ".."))
            if hasattr(os, "add_dll_directory"):
                try:
                    os.add_dll_directory(jvm_bin_dir)
                except Exception:
                    pass
            if jvm_bin_dir not in os.environ.get("PATH", ""):
                os.environ["PATH"] = jvm_bin_dir + os.pathsep + os.environ.get("PATH", "")

            jpype.startJVM(
                jvm_path,
                "-Djava.awt.headless=true",
                "-Dorg.apache.logging.log4j.simplelog.StatusLogger.level=OFF",
                classpath=jars
            )
            _jvm_initialized = True
            logger.info("MPXJ JVM started successfully with %s (headless mode, dll dir registered)", jvm_path)
            return True
        else:
            logger.warning("JVM path not found at %s. .mpp parsing unavailable; .xml fallback available.", jvm_path)
            return False
    except Exception as e:
        logger.warning("Failed to initialize MPXJ JVM: %s", e)
        return False


def parse_project_file(file_bytes: bytes, filename: str) -> Dict[str, Any]:
    """
    Parses an uploaded project schedule file (.mpp or .xml).
    Extracts summary task metrics, project properties, and resource assignments.
    """
    ext = os.path.splitext(filename.lower())[1]

    if ext == ".xml":
        # First try fast native XML parser, fallback to MPXJ if needed
        try:
            return parse_project_xml(file_bytes)
        except Exception as e:
            logger.info("Native XML parse failed (%s), trying MPXJ reader...", e)

    # For .mpp or complex XML files, use MPXJ
    if _init_mpxj():
        return parse_with_mpxj(file_bytes, filename)

    if ext == ".xml":
        return parse_project_xml(file_bytes)

    raise ValueError(f"Unable to parse '{filename}'. Java Virtual Machine is required to read binary .mpp files.")


def parse_project_xml(file_bytes: bytes) -> Dict[str, Any]:
    """
    Pure Python MSPDI XML parser for extracting summary metrics, resources, and custom field values.
    """
    root = ET.fromstring(file_bytes.decode("utf-8", errors="replace"))

    # Determine namespace
    ns_uri = ""
    if root.tag.startswith("{"):
        ns_uri = root.tag.split("}")[0].strip("{")
    ns = {"ms": ns_uri} if ns_uri else {}
    prefix = "ms:" if ns_uri else ""

    def find_text(el, path, default=None):
        if el is None:
            return default
        node = el.find(path, ns) if ns else el.find(path)
        return node.text.strip() if node is not None and node.text else default

    # Project title / properties
    title = find_text(root, f"{prefix}Title") or find_text(root, f"{prefix}Name")

    # Locate Task 0 / Project Summary Task
    tasks = root.findall(f".//{prefix}Task", ns) if ns else root.findall(".//Task")
    task_0 = None
    for t in tasks:
        uid = find_text(t, f"{prefix}UID")
        tid = find_text(t, f"{prefix}ID")
        if uid == "0" or tid == "0":
            task_0 = t
            break

    # If no task 0, take first summary task or first task
    if task_0 is None and tasks:
        for t in tasks:
            summary = find_text(t, f"{prefix}Summary")
            if summary == "1":
                task_0 = t
                break
        if task_0 is None:
            task_0 = tasks[0]

    def parse_float(val, default=0.0):
        try:
            return float(val) if val is not None else default
        except (ValueError, TypeError):
            return default

    def parse_date(val):
        if not val:
            return None
        # Handle 2026-08-31T08:00:00
        val_clean = val.split("T")[0]
        try:
            return date.fromisoformat(val_clean)
        except Exception:
            return None

    percent_complete = parse_float(find_text(task_0, f"{prefix}PercentComplete"))
    percent_work_complete = parse_float(find_text(task_0, f"{prefix}PercentWorkComplete"))
    start_date = parse_date(find_text(task_0, f"{prefix}Start"))
    finish_date = parse_date(find_text(task_0, f"{prefix}Finish"))
    baseline_finish = parse_date(find_text(task_0, f"{prefix}Baseline/{prefix}Finish"))
    actual_cost = parse_float(find_text(task_0, f"{prefix}ActualCost"))
    cost = parse_float(find_text(task_0, f"{prefix}Cost"))
    baseline_cost = parse_float(find_text(task_0, f"{prefix}BaselineCost") or find_text(task_0, f"{prefix}Baseline/{prefix}Cost"))
    baseline_budget = parse_float(find_text(task_0, f"{prefix}BaselineBudget") or find_text(task_0, f"{prefix}Baseline/{prefix}BudgetCost"))

    # Extract ERP Project Number from Task 0 ExtendedAttribute
    erp_number = None
    if task_0 is not None:
        ext_attrs = task_0.findall(f"{prefix}ExtendedAttribute", ns) if ns else task_0.findall("ExtendedAttribute")
        for ea in ext_attrs:
            fid = find_text(ea, f"{prefix}FieldID")
            val = find_text(ea, f"{prefix}Value")
            if fid == "188743731" and val:  # Task Text1 (ERP Project Number)
                erp_number = val

    # Resources
    resources_list = []
    res_nodes = root.findall(f".//{prefix}Resource", ns) if ns else root.findall(".//Resource")
    for r in res_nodes:
        uid_str = find_text(r, f"{prefix}UID")
        name_str = find_text(r, f"{prefix}Name")
        if not uid_str or uid_str == "0" or not name_str:
            continue
        is_generic = find_text(r, f"{prefix}IsGeneric") == "1"
        is_cost = find_text(r, f"{prefix}Type") == "2"
        resources_list.append({
            "uid": int(uid_str),
            "name": name_str,
            "is_generic": is_generic,
            "is_cost": is_cost,
        })

    return {
        "title": title,
        "erp_number": erp_number,
        "percent_complete": percent_complete,
        "percent_work_complete": percent_work_complete,
        "start_date": start_date,
        "finish_date": finish_date,
        "baseline_finish": baseline_finish,
        "actual_cost": actual_cost,
        "cost": cost,
        "baseline_cost": baseline_cost,
        "baseline_budget": baseline_budget,
        "resources": resources_list,
    }


def parse_with_mpxj(file_bytes: bytes, filename: str) -> Dict[str, Any]:
    """
    Parses a project schedule using MPXJ Java UniversalProjectReader.
    """
    import jpype
    import tempfile

    # Save bytes to temporary file for MPXJ reader
    suffix = os.path.splitext(filename)[1] or ".mpp"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name

    if not _init_mpxj():
        raise RuntimeError("Java Virtual Machine (JVM) could not be started for MPXJ.")

    try:
        UniversalProjectReader = jpype.JClass("org.mpxj.reader.UniversalProjectReader")
        reader = UniversalProjectReader()
        project_file = reader.read(tmp_path)

        props = project_file.getProjectProperties()
        title = str(props.getProjectTitle()) if props.getProjectTitle() else None

        # Retrieve tasks
        tasks = project_file.getTasks()
        task_0 = None
        if tasks.size() > 0:
            task_0 = tasks.get(0)

        def j_float(val):
            if val is None:
                return 0.0
            try:
                return float(str(val))
            except Exception:
                return 0.0

        def j_date(dt):
            if dt is None:
                return None
            try:
                s = str(dt).split("T")[0]
                return date.fromisoformat(s)
            except Exception:
                return None

        percent_complete = j_float(task_0.getPercentageComplete()) if task_0 else 0.0
        percent_work_complete = j_float(task_0.getPercentageWorkComplete()) if task_0 else 0.0
        start_date = j_date(task_0.getStart()) if task_0 else None
        finish_date = j_date(task_0.getFinish()) if task_0 else None
        baseline_finish = j_date(task_0.getBaselineFinish()) if task_0 else None

        actual_cost = j_float(task_0.getActualCost()) if task_0 else 0.0
        cost = j_float(task_0.getCost()) if task_0 else 0.0
        baseline_cost = j_float(task_0.getBaselineCost()) if task_0 else 0.0
        baseline_budget = j_float(task_0.getBaselineBudgetCost()) if task_0 else 0.0

        # ERP Number check from Task Text1
        erp_number = None
        if task_0:
            try:
                t1 = task_0.getText(1)
                if t1:
                    erp_number = str(t1).strip()
            except Exception:
                pass

        # Resources list
        resources_list = []
        res_list = project_file.getResources()
        for i in range(res_list.size()):
            r = res_list.get(i)
            uid = r.getUniqueID()
            name = str(r.getName()) if r.getName() else None
            if uid is None or uid == 0 or not name:
                continue
            is_gen = bool(r.getGeneric()) if r.getGeneric() is not None else False
            resources_list.append({
                "uid": int(str(uid)),
                "name": name,
                "is_generic": is_gen,
                "is_cost": False,
            })

        return {
            "title": title,
            "erp_number": erp_number,
            "percent_complete": percent_complete,
            "percent_work_complete": percent_work_complete,
            "start_date": start_date,
            "finish_date": finish_date,
            "baseline_finish": baseline_finish,
            "actual_cost": actual_cost,
            "cost": cost,
            "baseline_cost": baseline_cost,
            "baseline_budget": baseline_budget,
            "resources": resources_list,
        }
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass
