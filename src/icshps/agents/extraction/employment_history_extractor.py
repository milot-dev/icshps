from __future__ import annotations

from pathlib import Path
import re

from icshps.schemas.profile import EmploymentRecord


EMPLOYMENT_CONFIDENCE = 0.80
PARTIAL_EMPLOYMENT_CONFIDENCE = 0.60

MONTHS = {
    "jan": "01",
    "january": "01",
    "feb": "02",
    "february": "02",
    "mar": "03",
    "march": "03",
    "apr": "04",
    "april": "04",
    "may": "05",
    "jun": "06",
    "june": "06",
    "jul": "07",
    "july": "07",
    "aug": "08",
    "august": "08",
    "sep": "09",
    "sept": "09",
    "september": "09",
    "oct": "10",
    "october": "10",
    "nov": "11",
    "november": "11",
    "dec": "12",
    "december": "12",
}

DATE_TOKEN_PATTERN = (
    r"(?:\d{4}-\d{2}-\d{2}|\d{4}-\d{2}|"
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t)?(?:ember)?|Oct(?:ober)?|Nov(?:ember)?|"
    r"Dec(?:ember)?)\s+\d{4}|\d{4}|Present|Current|Now)"
)
DATE_RANGE_RE = re.compile(
    rf"(?P<start>{DATE_TOKEN_PATTERN})\s*"
    rf"(?:-|\u2013|\u2014|\bto\b)\s*(?P<end>{DATE_TOKEN_PATTERN})",
    re.IGNORECASE,
)

CURRENT_DATE_TOKENS = {"present", "current", "now"}
SECTION_HEADERS = {
    "experience",
    "employment",
    "employment history",
    "work experience",
    "professional experience",
}
STOP_HEADERS = {
    "education",
    "skills",
    "certifications",
    "certification",
    "projects",
    "summary",
    "profile",
}
INLINE_SECTION_LABEL_RE = re.compile(r"^\s*(experience|employment|employment history|work experience|professional experience)\s*:\s*(.+)$", re.IGNORECASE)
JOB_TITLE_KEYWORDS = {
    "analyst",
    "architect",
    "backend",
    "consultant",
    "data",
    "developer",
    "engineer",
    "lead",
    "manager",
    "scientist",
    "software",
    "specialist",
}


def extract_employment_history(
    lines: list[str],
    source_path: Path,
    make_evidence,
) -> list[EmploymentRecord]:
    records: list[EmploymentRecord] = []
    in_section = False

    for line in lines:
        inline_section_line = inline_employment_section_line(line)
        if inline_section_line is not None:
            in_section = True
            record = parse_employment_line(
                inline_section_line,
                source_path,
                len(records),
                make_evidence,
            )
            if record is not None:
                records.append(record)
            continue

        header = normalize_section_header(line)
        if header in SECTION_HEADERS:
            in_section = True
            continue

        if in_section and header in STOP_HEADERS:
            break

        if not in_section:
            continue

        record = parse_employment_line(line, source_path, len(records), make_evidence)
        if record is not None:
            records.append(record)

    return records


def parse_employment_line(
    line: str,
    source_path: Path,
    record_index: int,
    make_evidence,
) -> EmploymentRecord | None:
    date_range = extract_date_range(line)
    if date_range is None:
        return None

    start_date, end_date, is_current = date_range
    remainder = DATE_RANGE_RE.sub("", line).strip(" ,-\u2013\u2014")
    company, title = parse_company_and_title(remainder)
    if not company and not title:
        return None

    confidence = (
        EMPLOYMENT_CONFIDENCE
        if company and title and start_date and (end_date or is_current)
        else PARTIAL_EMPLOYMENT_CONFIDENCE
    )

    return EmploymentRecord(
        company=company or title or "Unknown Company",
        title=title,
        start_date=start_date,
        end_date=end_date,
        is_current=is_current,
        confidence=confidence,
        evidence=[
            make_evidence(
                source_path,
                record_index,
                line,
                confidence,
            )
        ],
    )


def parse_company_and_title(value: str) -> tuple[str | None, str | None]:
    if " at " in value.lower():
        parts = re.split(r"\s+at\s+", value, maxsplit=1, flags=re.IGNORECASE)
        return clean_value(parts[1] if len(parts) > 1 else None), clean_value(parts[0])

    if "," in value:
        parts = [part for part in (clean_value(part) for part in value.split(",")) if part]
        if len(parts) >= 2:
            return parts[1], parts[0]

    if " - " in value:
        parts = [part for part in (clean_value(part) for part in value.split(" - ")) if part]
        if len(parts) >= 2:
            return parts[0], parts[1]

    parts = [part for part in value.split() if part]
    if len(parts) >= 3 and any(_is_job_title_token(part) for part in parts[1:]):
        return clean_value(parts[0]), clean_value(" ".join(parts[1:]))

    return None, None


def extract_date_range(line: str) -> tuple[str | None, str | None, bool] | None:
    match = DATE_RANGE_RE.search(line)
    if match is None:
        return None

    start_date = normalize_date(match.group("start"))
    raw_end_date = match.group("end")
    is_current = raw_end_date.strip().lower() in CURRENT_DATE_TOKENS
    end_date = None if is_current else normalize_date(raw_end_date)
    return start_date, end_date, is_current


def normalize_date(value: str) -> str | None:
    normalized = value.strip()
    lowered = normalized.lower()
    if lowered in CURRENT_DATE_TOKENS:
        return None

    if re.fullmatch(r"\d{4}(?:-\d{2})?(?:-\d{2})?", normalized):
        return normalized

    match = re.fullmatch(r"([A-Za-z]+)\s+(\d{4})", normalized)
    if match is None:
        return normalized

    month = MONTHS.get(match.group(1).lower())
    return f"{match.group(2)}-{month}" if month else normalized


def normalize_section_header(line: str) -> str:
    return re.sub(r"[^a-z ]+", "", line.lower()).strip()


def inline_employment_section_line(line: str) -> str | None:
    match = INLINE_SECTION_LABEL_RE.match(line)
    if match is None:
        return None

    return clean_value(match.group(2))


def clean_value(value: str | None) -> str | None:
    if value is None:
        return None

    cleaned = re.sub(r"\s+", " ", value).strip(" ,-\u2013\u2014")
    return cleaned or None


def _is_job_title_token(value: str) -> bool:
    normalized = re.sub(r"[^a-z]+", "", value.lower())
    return normalized in JOB_TITLE_KEYWORDS
