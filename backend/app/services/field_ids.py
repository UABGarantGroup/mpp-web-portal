"""
Microsoft Project Field ID mapping constants and helper utilities.
Conforms to Microsoft Project Data Interchange (MSPDI) specification and MPXJ standards.
"""

from typing import Dict, Tuple
from backend.app.models.enums import CustomFieldEntityEnum, CustomFieldTypeEnum

# Base offsets from MSPDI specification
TASK_FIELD_BASE = 0x0B400000      # 188743680
RESOURCE_FIELD_BASE = 0x0C400000  # 205520896
PROJECT_FIELD_BASE = 0x0B600000   # 190840832

# Task relative IDs
# Text1..Text10: 51, 54, 57, 60, 63, 66, 67, 68, 69, 70
# Text11..Text30: 317..336
TASK_TEXT_OFFSETS: Dict[int, int] = {
    1: 51, 2: 54, 3: 57, 4: 60, 5: 63,
    6: 66, 7: 67, 8: 68, 9: 69, 10: 70,
    11: 317, 12: 318, 13: 319, 14: 320, 15: 321,
    16: 322, 17: 323, 18: 324, 19: 325, 20: 326,
    21: 327, 22: 328, 23: 329, 24: 330, 25: 331,
    26: 332, 27: 333, 28: 334, 29: 335, 30: 336,
}

TASK_COST_OFFSETS: Dict[int, int] = {
    1: 106, 2: 107, 3: 108, 4: 109, 5: 110,
    6: 111, 7: 112, 8: 113, 9: 114, 10: 264,
}

TASK_FLAG_OFFSETS: Dict[int, int] = {
    1: 72, 2: 73, 3: 74, 4: 75, 5: 76,
    6: 77, 7: 78, 8: 79, 9: 80, 10: 81,
    11: 292, 12: 293, 13: 294, 14: 295, 15: 296,
    16: 297, 17: 298, 18: 299, 19: 300, 20: 301,
}

# Resource relative IDs
RESOURCE_TEXT_OFFSETS: Dict[int, int] = {
    1: 8, 2: 9, 3: 10, 4: 11, 5: 12,
    6: 13, 7: 14, 8: 15, 9: 16, 10: 101,
    11: 225, 12: 226, 13: 227, 14: 228, 15: 229,
    16: 230, 17: 231, 18: 232, 19: 233, 20: 234,
    21: 235, 22: 236, 23: 237, 24: 238, 25: 239,
    26: 240, 27: 241, 28: 242, 29: 243, 30: 244,
}

RESOURCE_COST_OFFSETS: Dict[int, int] = {
    1: 123, 2: 124, 3: 125, 4: 128, 5: 129,
    6: 130, 7: 131, 8: 132, 9: 133, 10: 172,
}

RESOURCE_FLAG_OFFSETS: Dict[int, int] = {
    1: 127, 2: 128, 3: 129, 4: 130, 5: 131,
    6: 132, 7: 133, 8: 134, 9: 135, 10: 126,
    11: 195, 12: 196, 13: 197, 14: 198, 15: 199,
    16: 200, 17: 201, 18: 202, 19: 203, 20: 204,
}


def get_field_id(
    entity: CustomFieldEntityEnum,
    field_type: CustomFieldTypeEnum,
    slot_number: int = 1
) -> Tuple[str, str]:
    """
    Returns (field_id_str, internal_field_name), e.g. ("188743731", "Text1")
    """
    slot = max(1, slot_number)
    if entity == CustomFieldEntityEnum.TASK:
        base = TASK_FIELD_BASE
        if field_type == CustomFieldTypeEnum.TEXT:
            offset = TASK_TEXT_OFFSETS.get(slot, 51)
            name = f"Text{slot}"
        elif field_type == CustomFieldTypeEnum.COST:
            offset = TASK_COST_OFFSETS.get(slot, 106)
            name = f"Cost{slot}"
        elif field_type == CustomFieldTypeEnum.FLAG:
            offset = TASK_FLAG_OFFSETS.get(slot, 72)
            name = f"Flag{slot}"
        else:
            offset = TASK_TEXT_OFFSETS.get(slot, 51)
            name = f"Text{slot}"
        return str(base + offset), name

    elif entity == CustomFieldEntityEnum.RESOURCE:
        base = RESOURCE_FIELD_BASE
        if field_type == CustomFieldTypeEnum.TEXT:
            offset = RESOURCE_TEXT_OFFSETS.get(slot, 8)
            name = f"Text{slot}"
        elif field_type == CustomFieldTypeEnum.COST:
            offset = RESOURCE_COST_OFFSETS.get(slot, 123)
            name = f"Cost{slot}"
        elif field_type == CustomFieldTypeEnum.FLAG:
            offset = RESOURCE_FLAG_OFFSETS.get(slot, 127)
            name = f"Flag{slot}"
        else:
            offset = RESOURCE_TEXT_OFFSETS.get(slot, 8)
            name = f"Text{slot}"
        return str(base + offset), name

    else:
        # PROJECT entity custom fields mapped to Project Task 0 / enterprise text
        base = TASK_FIELD_BASE
        offset = TASK_TEXT_OFFSETS.get(slot, 51)
        return str(base + offset), f"Text{slot}"
