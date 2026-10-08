from enum import Enum


class RateTableEnum(str, Enum):
    A = "A"  # Internal Standard Rate
    B = "B"  # Overtime / Weekend Rate
    C = "C"  # Project / Billable Rate
    D = "D"  # Contractor / Specialized
    E = "E"  # Custom / Emergency


class ResourceTypeEnum(str, Enum):
    WORK = "Work"
    MATERIAL = "Material"
    COST = "Cost"


class ResourceKindEnum(str, Enum):
    NAMED = "Named"
    GENERIC = "Generic"


class StageStatusEnum(str, Enum):
    DONE = "Done"
    NOT_DONE = "Not done"
    NOT_APPLICABLE = "Not applicable"


class CustomFieldEntityEnum(str, Enum):
    TASK = "Task"
    RESOURCE = "Resource"
    PROJECT = "Project"


class CustomFieldTypeEnum(str, Enum):
    TEXT = "Text"
    NUMBER = "Number"
    COST = "Cost"
    DATE = "Date"
    FLAG = "Flag"
