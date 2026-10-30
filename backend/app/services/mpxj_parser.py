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


def _find_jvm_path() -> Optional[str]:
    """
    Locates the Java Virtual Machine shared library (jvm.dll or libjvm.so).
    Checks configuration, JAVA_HOME, common Windows installation paths, and jpype defaults.
    """
    from backend.app.core.config import settings

    # 1. Configured JVM path
    if settings.JVM_PATH and os.path.exists(settings.JVM_PATH):
        return settings.JVM_PATH

    # 2. JAVA_HOME environment variable
    java_home = os.environ.get("JAVA_HOME")
    if java_home:
        candidates = [
            os.path.join(java_home, "bin", "server", "jvm.dll"),
            os.path.join(java_home, "lib", "server", "libjvm.so"),
            os.path.join(java_home, "lib", "server", "libjvm.dylib"),
        ]
        for c in candidates:
            if os.path.exists(c):
                return c

    # 3. Common Windows JDK / JRE / Android Studio runtime locations
    if os.name == "nt":
        common_candidates = [
            r"C:\Program Files\Android\Android Studio\jbr\bin\server\jvm.dll",
            r"C:\Program Files\Java",
            r"C:\Program Files\Eclipse Adoptium",
            r"C:\Program Files\Microsoft",
            r"C:\Program Files\Amazon Corretto",
        ]
        for candidate in common_candidates:
            if os.path.isfile(candidate):
                return candidate
            if os.path.isdir(candidate):
                for root, _, files in os.walk(candidate):
                    if "jvm.dll" in files:
                        return os.path.join(root, "jvm.dll")

    # 4. Fallback to jpype default JVM path (standard on Linux/Docker)
    try:
        import jpype
        default_path = jpype.getDefaultJVMPath()
        if default_path and os.path.exists(default_path):
            return default_path
    except Exception as e:
        logger.debug("jpype.getDefaultJVMPath() exception: %s", e)

    return None


def _init_mpxj():
    global _jvm_initialized
    if _jvm_initialized:
        return True

    try:
        import jpype
        if jpype.isJVMStarted():
            _jvm_initialized = True
            return True

        import mpxj

        mpxj_dir = os.path.join(os.path.dirname(mpxj.__file__), "lib")
        jars = [os.path.join(mpxj_dir, f) for f in os.listdir(mpxj_dir) if f.endswith(".jar")]

        jvm_path = _find_jvm_path()
        if not jvm_path or not os.path.exists(jvm_path):
            logger.warning("JVM path not found (checked settings.JVM_PATH, JAVA_HOME, system paths, and jpype defaults). .mpp parsing unavailable; .xml fallback available.")
            return False

        # Windows-specific DLL directory discovery for Java runtime
        if os.name == "nt":
            jvm_dir = os.path.dirname(jvm_path)
            jvm_bin_dir = os.path.abspath(os.path.join(jvm_dir, ".."))
            if hasattr(os, "add_dll_directory"):
                try:
                    os.add_dll_directory(jvm_dir)
                    os.add_dll_directory(jvm_bin_dir)
                except Exception:
                    pass
            current_path = os.environ.get("PATH", "")
            if jvm_bin_dir not in current_path:
                os.environ["PATH"] = jvm_bin_dir + os.pathsep + current_path

        # Python's faulthandler registers a first-chance VectoredExceptionHandler on Windows
        # which logs HotSpot JVM's normal internal guard-page probing. Pause faulthandler during startup.
        import faulthandler
        fault_was_enabled = faulthandler.is_enabled()
        if fault_was_enabled:
            faulthandler.disable()

        try:
            jpype.startJVM(
                jvm_path,
                "-Djava.awt.headless=true",
                "-Dorg.apache.logging.log4j.simplelog.StatusLogger.level=OFF",
                classpath=jars
            )
        finally:
            if fault_was_enabled:
                faulthandler.enable()

        _jvm_initialized = True
        logger.info("MPXJ JVM started successfully with %s (headless mode)", jvm_path)
        return True
    except Exception as e:
        logger.warning("Failed to initialize MPXJ JVM: %s", e)
        return False


def _safe_parse_xml_bytes(file_bytes: bytes) -> ET.Element:
    """
    Safely parses XML bytes while blocking XML External Entities (XXE) and
    DOCTYPE / ENTITY expansion ('Billion Laughs' DoS) attacks.
    """
    xml_str = file_bytes.decode("utf-8", errors="replace")
    upper_head = xml_str[:4096].upper()
    if "<!DOCTYPE" in upper_head or "<!ENTITY" in upper_head:
        raise ValueError("Security violation: XML DOCTYPE and ENTITY declarations are forbidden.")

    try:
        import defusedxml.ElementTree as DefusedET
        return DefusedET.fromstring(xml_str)
    except ImportError:
        return ET.fromstring(xml_str)


def parse_project_file(file_bytes: bytes, filename: str) -> Dict[str, Any]:
    """
    Parses an uploaded project schedule file (.mpp or .xml).
    Extracts summary task metrics, project properties, and resource assignments.
    """
    safe_name = os.path.basename(filename or "")
    ext = os.path.splitext(safe_name.lower())[1]
    if ext not in (".mpp", ".xml"):
        raise ValueError(f"Unsupported schedule file extension '{ext}'. Only .mpp and .xml files are allowed.")

    if ext == ".xml":
        # Check for XXE / Entity expansion before any parser touches the XML
        _safe_parse_xml_bytes(file_bytes)
        # First try fast native XML parser, fallback to MPXJ if needed
        try:
            return parse_project_xml(file_bytes)
        except ValueError:
            raise
        except Exception as e:
            logger.info("Native XML parse failed (%s), trying MPXJ reader...", e)

    # For .mpp or complex XML files, use MPXJ
    if _init_mpxj():
        return parse_with_mpxj(file_bytes, safe_name)

    if ext == ".xml":
        return parse_project_xml(file_bytes)

    raise ValueError(f"Unable to parse '{safe_name}'. Java Virtual Machine is required to read binary .mpp files.")


def parse_project_xml(file_bytes: bytes) -> Dict[str, Any]:
    """
    Pure Python MSPDI XML parser for extracting summary metrics, resources, and custom field values.
    """
    root = _safe_parse_xml_bytes(file_bytes)

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

    task_0_name = find_text(task_0, f"{prefix}Name") if task_0 is not None else None
    task_0_notes = find_text(task_0, f"{prefix}Notes") if task_0 is not None else None

    def parse_float(val, default=0.0):
        try:
            return float(val) if val is not None else default
        except (ValueError, TypeError):
            return default

    def parse_iso_hours(val, default=0.0):
        if not val or not isinstance(val, str):
            return default
        import re
        m = re.match(r"^PT(?:(\d+(?:\.\d+)?)H)?(?:(\d+(?:\.\d+)?)M)?(?:(\d+(?:\.\d+)?)S)?$", val.strip())
        if not m:
            return default
        h = float(m.group(1) or 0.0)
        mins = float(m.group(2) or 0.0)
        secs = float(m.group(3) or 0.0)
        return h + (mins / 60.0) + (secs / 3600.0)

    def parse_date(val):
        if not val:
            return None
        # Handle 2026-08-31T08:00:00
        val_clean = val.split("T")[0]
        try:
            return date.fromisoformat(val_clean)
        except Exception:
            return None

    # 1. Collect resources and identify Budget Resources (Type=2/Cost, IsBudget=1)
    resources_list = []
    budget_resource_uids = set()
    res_nodes = root.findall(f".//{prefix}Resource", ns) if ns else root.findall(".//Resource")
    for r in res_nodes:
        uid_str = find_text(r, f"{prefix}UID")
        name_str = find_text(r, f"{prefix}Name")
        if not uid_str or uid_str == "0" or not name_str:
            continue
        is_generic = find_text(r, f"{prefix}IsGeneric") == "1"
        is_cost = find_text(r, f"{prefix}Type") == "2"
        is_budget = find_text(r, f"{prefix}IsBudget") == "1"
        if is_budget or "budget" in name_str.lower():
            budget_resource_uids.add(uid_str)
        resources_list.append({
            "uid": int(uid_str),
            "name": name_str,
            "is_generic": is_generic,
            "is_cost": is_cost,
            "is_budget": is_budget,
        })

    # 2. Inspect Assignments for Task 0 budget resource assignments and non-budget baseline cost
    asgn_nodes = root.findall(f".//{prefix}Assignment", ns) if ns else root.findall(".//Assignment")
    task_0_budget_cost = 0.0
    task_0_baseline_budget = 0.0
    total_nonbudget_asgn_baseline = 0.0

    for asgn in asgn_nodes:
        t_uid = find_text(asgn, f"{prefix}TaskUID")
        r_uid = find_text(asgn, f"{prefix}ResourceUID")
        b_cost = parse_float(find_text(asgn, f"{prefix}BudgetCost"))
        cost_val = parse_float(find_text(asgn, f"{prefix}Cost"))

        # Look for baseline values on assignment
        base_cost_val = parse_float(find_text(asgn, f"{prefix}BaselineCost") or find_text(asgn, f"{prefix}Baseline/{prefix}Cost"))
        base_b_cost_val = parse_float(find_text(asgn, f"{prefix}BaselineBudgetCost") or find_text(asgn, f"{prefix}Baseline/{prefix}BudgetCost"))

        # Check nested <Baseline> elements
        baselines = asgn.findall(f"{prefix}Baseline", ns) if ns else asgn.findall("Baseline")
        for b in baselines:
            if base_cost_val == 0.0:
                base_cost_val = parse_float(find_text(b, f"{prefix}Cost"))
            if base_b_cost_val == 0.0:
                base_b_cost_val = parse_float(find_text(b, f"{prefix}BudgetCost") or find_text(b, f"{prefix}Cost"))

        is_budget_asgn = (r_uid in budget_resource_uids) or (b_cost > 0.0)

        # In MS Project, budget resources are assigned strictly to Task 0
        if (t_uid == "0" or t_uid is None) and is_budget_asgn:
            task_0_budget_cost += (b_cost if b_cost > 0.0 else cost_val)
            task_0_baseline_budget += (base_b_cost_val if base_b_cost_val > 0.0 else base_cost_val)
        elif not is_budget_asgn:
            total_nonbudget_asgn_baseline += base_cost_val

    # 3. Extract Task 0 project summary metrics
    percent_complete = parse_float(find_text(task_0, f"{prefix}PercentComplete"))
    percent_work_complete = parse_float(find_text(task_0, f"{prefix}PercentWorkComplete"))
    start_date = parse_date(find_text(task_0, f"{prefix}Start"))
    finish_date = parse_date(find_text(task_0, f"{prefix}Finish"))

    # Baseline finish: check direct element, sub-element, or nested <Baseline>
    baseline_finish = parse_date(find_text(task_0, f"{prefix}BaselineFinish") or find_text(task_0, f"{prefix}Baseline/{prefix}Finish"))
    if not baseline_finish and task_0 is not None:
        t0_baselines = task_0.findall(f"{prefix}Baseline", ns) if ns else task_0.findall("Baseline")
        for b in t0_baselines:
            bf = parse_date(find_text(b, f"{prefix}Finish"))
            if bf:
                baseline_finish = bf
                break

    actual_cost = parse_float(find_text(task_0, f"{prefix}ActualCost"))
    cost = parse_float(find_text(task_0, f"{prefix}Cost"))

    # Baseline cost: In MS Project, Task 0 BaselineCost represents the work/resource baseline cost
    baseline_cost = parse_float(find_text(task_0, f"{prefix}BaselineCost") or find_text(task_0, f"{prefix}Baseline/{prefix}Cost"))
    if baseline_cost == 0.0 and task_0 is not None:
        t0_baselines = task_0.findall(f"{prefix}Baseline", ns) if ns else task_0.findall("Baseline")
        for b in t0_baselines:
            b_cost = parse_float(find_text(b, f"{prefix}Cost"))
            if b_cost > 0.0:
                baseline_cost = b_cost
                break

    # If Task 0 summary metrics are 0.0, roll up from leaf tasks (MS Project calculation logic)
    if tasks:
        leaf_baseline_sum = 0.0
        leaf_cost_sum = 0.0
        leaf_actual_cost_sum = 0.0
        leaf_dur_sum = 0.0
        leaf_act_dur_sum = 0.0
        leaf_work_sum = 0.0
        leaf_act_work_sum = 0.0
        leaf_starts = []
        leaf_finishes = []
        for t in tasks:
            t_uid = find_text(t, f"{prefix}UID")
            t_id = find_text(t, f"{prefix}ID")
            if t_uid == "0" or t_id == "0":
                continue
            is_summary = find_text(t, f"{prefix}Summary") == "1"
            if not is_summary:
                t_bc = parse_float(find_text(t, f"{prefix}BaselineCost") or find_text(t, f"{prefix}Baseline/{prefix}Cost"))
                if t_bc == 0.0:
                    t_baselines = t.findall(f"{prefix}Baseline", ns) if ns else t.findall("Baseline")
                    for b in t_baselines:
                        bc = parse_float(find_text(b, f"{prefix}Cost"))
                        if bc > 0.0:
                            t_bc = bc
                            break
                leaf_baseline_sum += t_bc
                leaf_cost_sum += parse_float(find_text(t, f"{prefix}Cost"))
                leaf_actual_cost_sum += parse_float(find_text(t, f"{prefix}ActualCost"))

                t_dur = parse_iso_hours(find_text(t, f"{prefix}Duration"))
                t_act_dur = parse_iso_hours(find_text(t, f"{prefix}ActualDuration"))
                t_pct = parse_float(find_text(t, f"{prefix}PercentComplete"))
                if t_dur == 0.0 and t_pct > 0.0:
                    t_dur = 1.0
                if t_act_dur == 0.0 and t_dur > 0.0 and t_pct > 0.0:
                    t_act_dur = t_dur * (t_pct / 100.0)
                leaf_dur_sum += t_dur
                leaf_act_dur_sum += t_act_dur

                t_work = parse_iso_hours(find_text(t, f"{prefix}Work"))
                t_act_work = parse_iso_hours(find_text(t, f"{prefix}ActualWork"))
                t_wpct = parse_float(find_text(t, f"{prefix}PercentWorkComplete"))
                if t_work == 0.0 and t_wpct > 0.0:
                    t_work = 1.0
                if t_act_work == 0.0 and t_work > 0.0 and t_wpct > 0.0:
                    t_act_work = t_work * (t_wpct / 100.0)
                leaf_work_sum += t_work
                leaf_act_work_sum += t_act_work

                ts = parse_date(find_text(t, f"{prefix}Start"))
                tf = parse_date(find_text(t, f"{prefix}Finish"))
                if ts:
                    leaf_starts.append(ts)
                if tf:
                    leaf_finishes.append(tf)

        if baseline_cost == 0.0:
            if leaf_baseline_sum > 0.0:
                baseline_cost = leaf_baseline_sum
            elif total_nonbudget_asgn_baseline > 0.0:
                baseline_cost = total_nonbudget_asgn_baseline
        if cost == 0.0 and leaf_cost_sum > 0.0:
            cost = leaf_cost_sum
        if actual_cost == 0.0 and leaf_actual_cost_sum > 0.0:
            actual_cost = leaf_actual_cost_sum
        if percent_complete == 0.0 and leaf_dur_sum > 0.0 and leaf_act_dur_sum > 0.0:
            percent_complete = round((leaf_act_dur_sum / leaf_dur_sum) * 100.0, 1)
        if percent_work_complete == 0.0 and leaf_work_sum > 0.0 and leaf_act_work_sum > 0.0:
            percent_work_complete = round((leaf_act_work_sum / leaf_work_sum) * 100.0, 1)
        if not start_date and leaf_starts:
            start_date = min(leaf_starts)
        if leaf_finishes and (not finish_date or max(leaf_finishes) > finish_date):
            finish_date = max(leaf_finishes)

    # Budget cost & Baseline budget cost
    budget_cost = parse_float(find_text(task_0, f"{prefix}BudgetCost")) or task_0_budget_cost
    baseline_budget = parse_float(find_text(task_0, f"{prefix}BaselineBudget") or find_text(task_0, f"{prefix}Baseline/{prefix}BudgetCost")) or task_0_baseline_budget

    # Extract ERP Project Number and Technical PortalProjectGUID from Task 0 ExtendedAttributes and GUID
    erp_number = None
    portal_project_guid = None
    task_0_guid = find_text(task_0, f"{prefix}GUID") if task_0 is not None else None
    project_props_guid = find_text(root, f"{prefix}GUID")
    if task_0 is not None:
        ext_attrs = task_0.findall(f"{prefix}ExtendedAttribute", ns) if ns else task_0.findall("ExtendedAttribute")
        for ea in ext_attrs:
            fid = find_text(ea, f"{prefix}FieldID")
            val = find_text(ea, f"{prefix}Value")
            if fid == "188743731" and val:  # Task Text1 (ERP Project Number)
                erp_number = val
            elif fid in ("188744016", "188744017") and val:  # Task Text30 (PortalProjectGUID)
                portal_project_guid = val

    tech_guids = []
    for g in (portal_project_guid, task_0_guid, project_props_guid):
        if g and str(g).strip() and str(g).strip() not in tech_guids:
            tech_guids.append(str(g).strip())

    return {
        "title": title,
        "task_name": task_0_name or title,
        "notes": task_0_notes,
        "erp_number": erp_number,
        "portal_project_guid": portal_project_guid,
        "project_guid": tech_guids[0] if tech_guids else None,
        "technical_guids": tech_guids,
        "percent_complete": percent_complete,
        "percent_work_complete": percent_work_complete,
        "start_date": start_date,
        "finish_date": finish_date,
        "baseline_finish": baseline_finish,
        "actual_cost": actual_cost,
        "cost": cost,
        "baseline_cost": baseline_cost,
        "baseline_budget": baseline_budget,
        "budget_cost": budget_cost,
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

        # Retrieve tasks and locate Project Summary Task (UID=0 or ID=0)
        tasks = project_file.getTasks()
        task_0 = None
        if tasks.size() > 0:
            for idx in range(tasks.size()):
                cand = tasks.get(idx)
                if cand.getUniqueID() == 0 or cand.getID() == 0:
                    task_0 = cand
                    break
            if task_0 is None:
                task_0 = tasks.get(0)

        task_0_name = str(task_0.getName()).strip() if (task_0 and task_0.getName()) else None
        task_0_notes = str(task_0.getNotes()).strip() if (task_0 and task_0.getNotes()) else None

        def j_float(val):
            if val is None:
                return 0.0
            try:
                return float(str(val))
            except Exception:
                return 0.0

        def j_duration_num(dur_obj):
            if dur_obj is None:
                return 0.0
            try:
                return float(dur_obj.getDuration())
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
        budget_cost = j_float(task_0.getBudgetCost()) if task_0 else 0.0

        # Inspect Task 0 assignments for budget resource & baseline budget
        if task_0:
            try:
                asgns = task_0.getResourceAssignments()
                if asgns:
                    for i in range(asgns.size()):
                        asgn = asgns.get(i)
                        res = asgn.getResource()
                        is_budget_res = bool(res.getBudget()) if (res and res.getBudget() is not None) else False
                        asgn_b_cost = j_float(asgn.getBudgetCost())
                        asgn_cost = j_float(asgn.getCost())
                        asgn_base_b_cost = j_float(asgn.getBaselineBudgetCost())
                        asgn_base_cost = j_float(asgn.getBaselineCost())

                        if is_budget_res or asgn_b_cost > 0.0:
                            if budget_cost == 0.0:
                                budget_cost += (asgn_b_cost if asgn_b_cost > 0.0 else asgn_cost)
                            if baseline_budget == 0.0:
                                baseline_budget += (asgn_base_b_cost if asgn_base_b_cost > 0.0 else asgn_base_cost)
            except Exception as e:
                logger.debug("Error reading task 0 assignments in MPXJ: %s", e)

        # Roll up leaf task metrics if Task 0 was not recalculated by MS Project (e.g. Manual calculation mode)
        if tasks.size() > 1:
            total_leaf_baseline = 0.0
            total_leaf_cost = 0.0
            total_leaf_actual_cost = 0.0
            total_leaf_dur = 0.0
            total_leaf_act_dur = 0.0
            total_leaf_work = 0.0
            total_leaf_act_work = 0.0
            leaf_starts = []
            leaf_finishes = []

            for idx in range(tasks.size()):
                t = tasks.get(idx)
                if t.getUniqueID() == 0 or t.getID() == 0:
                    continue
                if not bool(t.getSummary()):
                    total_leaf_baseline += j_float(t.getBaselineCost())
                    total_leaf_cost += j_float(t.getCost())
                    total_leaf_actual_cost += j_float(t.getActualCost())

                    t_dur = j_duration_num(t.getDuration())
                    t_act_dur = j_duration_num(t.getActualDuration())
                    t_pct = j_float(t.getPercentageComplete())
                    if t_act_dur == 0.0 and t_dur > 0.0 and t_pct > 0.0:
                        t_act_dur = t_dur * (t_pct / 100.0)
                    total_leaf_dur += t_dur
                    total_leaf_act_dur += t_act_dur

                    t_work = j_duration_num(t.getWork())
                    t_act_work = j_duration_num(t.getActualWork())
                    t_wpct = j_float(t.getPercentageWorkComplete())
                    if t_act_work == 0.0 and t_work > 0.0 and t_wpct > 0.0:
                        t_act_work = t_work * (t_wpct / 100.0)
                    total_leaf_work += t_work
                    total_leaf_act_work += t_act_work

                    ts = j_date(t.getStart())
                    tf = j_date(t.getFinish())
                    if ts:
                        leaf_starts.append(ts)
                    if tf:
                        leaf_finishes.append(tf)

            if baseline_cost == 0.0 and total_leaf_baseline > 0.0:
                baseline_cost = total_leaf_baseline
            if cost == 0.0 and total_leaf_cost > 0.0:
                cost = total_leaf_cost
            if actual_cost == 0.0 and total_leaf_actual_cost > 0.0:
                actual_cost = total_leaf_actual_cost
            if percent_complete == 0.0 and total_leaf_dur > 0.0 and total_leaf_act_dur > 0.0:
                percent_complete = round((total_leaf_act_dur / total_leaf_dur) * 100.0, 1)
            if percent_work_complete == 0.0 and total_leaf_work > 0.0 and total_leaf_act_work > 0.0:
                percent_work_complete = round((total_leaf_act_work / total_leaf_work) * 100.0, 1)
            if not start_date and leaf_starts:
                start_date = min(leaf_starts)
            if leaf_finishes and (not finish_date or max(leaf_finishes) > finish_date):
                finish_date = max(leaf_finishes)

        # ERP Number & Technical PortalProjectGUID check from Task 0 and Project Properties
        erp_number = None
        portal_project_guid = None
        task_0_guid = None
        project_props_guid = None
        try:
            if props and props.getGUID():
                project_props_guid = str(props.getGUID()).strip()
        except Exception:
            pass

        if task_0:
            try:
                t1 = task_0.getText(1)
                if t1:
                    erp_number = str(t1).strip()
            except Exception:
                pass
            try:
                t30 = task_0.getText(30)
                if t30:
                    portal_project_guid = str(t30).strip()
            except Exception:
                pass
            try:
                if task_0.getGUID():
                    task_0_guid = str(task_0.getGUID()).strip()
            except Exception:
                pass

        tech_guids = []
        for g in (portal_project_guid, task_0_guid, project_props_guid):
            if g and g not in tech_guids:
                tech_guids.append(g)

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
            is_budget = bool(r.getBudget()) if r.getBudget() is not None else False
            resources_list.append({
                "uid": int(str(uid)),
                "name": name,
                "is_generic": is_gen,
                "is_cost": False,
                "is_budget": is_budget,
            })

        return {
            "title": title,
            "task_name": task_0_name or title,
            "notes": task_0_notes,
            "erp_number": erp_number,
            "portal_project_guid": portal_project_guid,
            "project_guid": tech_guids[0] if tech_guids else None,
            "technical_guids": tech_guids,
            "percent_complete": percent_complete,
            "percent_work_complete": percent_work_complete,
            "start_date": start_date,
            "finish_date": finish_date,
            "baseline_finish": baseline_finish,
            "actual_cost": actual_cost,
            "cost": cost,
            "baseline_cost": baseline_cost,
            "baseline_budget": baseline_budget,
            "budget_cost": budget_cost,
            "resources": resources_list,
        }
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass
