import re
from typing import Any


PERSON_TYPE_FIELD = "人员类型"
INTERVAL_FIELD = "区间"
NOTE_FIELD = "备注"

AGE_RANGE_NOTE_PREFIX = "年龄区间："

AGE_MARKER_RE = re.compile(r"(周岁|岁|年龄|投保年龄|参保年龄|出生|满\d+\s*天|天至|日至|个月)")
AGE_RANGE_RE = re.compile(
    r"((?:出生\s*满\s*)?\d+(?:\.\d+)?\s*(?:天|日|个月|月|周岁|岁)?\s*"
    r"(?:-|－|—|~|～|至|到)\s*"
    r"\d+(?:\.\d+)?\s*(?:天|日|个月|月|周岁|岁)?)"
    r"|(\d+(?:\.\d+)?\s*(?:周岁|岁))"
)
NUMBER_ONLY_RE = re.compile(r"^\d+(?:\.\d+)?$")
NUMERIC_RANGE_RE = re.compile(r"^\d+(?:\.\d+)?\s*(?:-|－|—|~|～|至|到)\s*\d+(?:\.\d+)?$")
AGE_OR_NUMBER_RE = re.compile(r"^\d+(?:\.\d+)?\s*(?:周岁|岁|天|日|个月|月)?$")

AMOUNT_UNIT_RE = re.compile(r"(元|万元|万|亿元)")
AMOUNT_RE = r"\d+(?:\.\d+)?\s*(?:元|万元|万|亿元)"
REIMBURSEMENT_INTERVAL_PATTERNS = [
    re.compile(rf"({AMOUNT_RE}\s*(?:-|－|—|~|～|至|到)\s*{AMOUNT_RE})"),
    re.compile(rf"(\d+(?:\.\d+)?\s*(?:-|－|—|~|～|至|到)\s*{AMOUNT_RE})"),
    re.compile(rf"({AMOUNT_RE}\s*(?:以上|以下|以内|及以上|及以下|起))"),
]


def clean_text_token(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).strip("：:，,。；;、（）()[]【】\"'“”‘’")


def extract_age_range(value: Any) -> str:
    text = clean_text_token(value)
    if not text or not AGE_MARKER_RE.search(text):
        return ""
    match = AGE_RANGE_RE.search(text)
    if not match:
        return ""
    return next((group for group in match.groups() if group), "").strip()


def is_age_range(value: Any) -> bool:
    return bool(extract_age_range(value))


def is_invalid_person_type(value: Any) -> bool:
    text = clean_text_token(value)
    if not text:
        return False
    if is_age_range(text):
        return True
    if NUMBER_ONLY_RE.fullmatch(text) or NUMERIC_RANGE_RE.fullmatch(text):
        return True
    if AGE_OR_NUMBER_RE.fullmatch(text) and AGE_MARKER_RE.search(text):
        return True
    return False


def normalize_person_type(value: Any) -> str:
    text = clean_text_token(value)
    if is_invalid_person_type(text):
        return ""
    return text


def extract_reimbursement_interval(value: Any) -> str:
    text = clean_text_token(value)
    if not text or is_age_range(text) or not AMOUNT_UNIT_RE.search(text):
        return ""
    for pattern in REIMBURSEMENT_INTERVAL_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(1).strip()
    return text if "区间" not in text and AMOUNT_UNIT_RE.search(text) else ""


def is_reimbursement_interval(value: Any) -> bool:
    return bool(extract_reimbursement_interval(value))


def age_range_note(value: Any) -> str:
    age_range = extract_age_range(value) or clean_text_token(value)
    return f"{AGE_RANGE_NOTE_PREFIX}{age_range}" if age_range else ""


def invalid_person_type_note(value: Any) -> str:
    if is_age_range(value):
        return age_range_note(value)
    text = clean_text_token(value)
    if NUMBER_ONLY_RE.fullmatch(text) or NUMERIC_RANGE_RE.fullmatch(text):
        return f"人员类型原值：{text}"
    return ""


def append_note(existing: Any, note: str) -> str:
    note = str(note or "").strip()
    if not note:
        return str(existing or "")
    current = str(existing or "").strip()
    if not current or current == "--":
        return note
    parts = [part for part in current.split("；") if part]
    if note in parts:
        return current
    return f"{current}；{note}"
