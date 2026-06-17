from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

from icshps.schemas import EducationRecord, EvidenceRef

EDUCATION_CONFIDENCE = 0.78

# Robust DEGREE_RE to match many forms of degrees: B.S., B.Sc., B.A., M.S., M.Sc., Ph.D., MBA, PhD, Associate, Bachelor, Master, Doctor, etc.
# Also handles 's and trailing spaces/words.
DEGREE_RE = re.compile(
    r"\b("
    r"(?:Bachelor|Master|Doctor|Doctorate|PhD|BSc|MSc|BA|MA|MBA|Associate|B\.Sc\.|M\.Sc\.|Ph\.D\.|B\.A\.|M\.A\.|B\.S\.|M\.S\.)"
    r"(?:'s)?"
    r"(?:\s+(?:of|degree|science|arts|engineering|business|computer|data|"
    r"information|technology|administration))*"
    r"(?:\s+in\s+[A-Za-z][A-Za-z\s&/-]+)?"
    r")\b",
    re.IGNORECASE,
)

YEAR_RE = re.compile(r"\b((?:19|20)\d{2})\b")

# More keywords to match local and international institution types
INSTITUTION_KEYWORDS = (
    "university",
    "college",
    "institute",
    "school",
    "academy",
    "faculty",
    "universiteti",
    "shkolla",
    "fakulteti",
    "gjimnazi",
    "lycee",
)

SECTION_STARTS = {
    "education",
    "academic background",
    "academic qualifications",
    "qualifications",
}

SECTION_END_PREFIXES = (
    "skills",
    "technical skills",
    "professional experience",
    "experience",
    "employment",
    "work history",
    "certifications",
    "certificates",
    "projects",
)

COUNTRY_HINTS = {
    "kosovo",
    "germany",
    "france",
    "italy",
    "spain",
    "united kingdom",
    "uk",
    "united states",
    "usa",
    "canada",
    "poland",
    "austria",
    "switzerland",
    "netherlands",
    "turkey",
    "albania",
}

LOCAL_COUNTRIES = {"kosovo"}

# Local institution/location keywords to help distinguish local vs international when country is omitted
LOCAL_KEYWORDS = {
    "prishtina",
    "pristina",
    "prishtine",
    "kosovo",
    "kosove",
    "kosova",
    "up",
    "ubt",
    "riinvest",
    "auk",
    "rit",
}

MakeEducationEvidence = Callable[[Path, int, str, float], EvidenceRef]


def extract_education_records(
    lines: list[str],
    source_path: Path,
    make_education_evidence: MakeEducationEvidence,
) -> list[EducationRecord]:
    """Extract structured education records from resume text lines."""
    candidate_lines = education_candidate_lines(lines)
    
    # Clean and filter candidate lines
    cleaned_lines = [clean_education_line(line) for line in candidate_lines]
    cleaned_lines = [line for line in cleaned_lines if line]
    
    # Group lines into blocks representing individual records
    blocks = group_lines_into_education_blocks(cleaned_lines)
    
    records: list[EducationRecord] = []
    
    for block in blocks:
        parsed = parse_education_block(block)
        if parsed is None:
            continue
            
        record_index = len(records)
        evidence_snippet = "\n".join(block)
        
        records.append(
            EducationRecord(
                institution=parsed.institution,
                degree=parsed.degree,
                field_of_study=parsed.field_of_study,
                country=parsed.country,
                start_year=parsed.start_year,
                end_year=parsed.end_year,
                is_international=parsed.is_international,
                confidence=EDUCATION_CONFIDENCE,
                evidence=[
                    make_education_evidence(
                        source_path,
                        record_index,
                        evidence_snippet,
                        EDUCATION_CONFIDENCE,
                    )
                ],
            )
        )
        
    return records


def education_candidate_lines(lines: list[str]) -> list[str]:
    """Identify lines in the resume text that contain education information."""
    in_section = False
    candidates: list[str] = []

    for line in lines:
        lowered = line.lower().strip(":")

        if lowered in SECTION_STARTS:
            in_section = True
            continue

        if in_section and lowered.startswith(SECTION_END_PREFIXES):
            in_section = False

        if in_section or looks_like_education_line(line):
            candidates.append(line)

    return candidates


def looks_like_education_line(line: str) -> bool:
    """Check if a line looks like it belongs to an education record."""
    lowered = line.lower()
    has_degree = DEGREE_RE.search(line) is not None
    has_institution = any(keyword in lowered for keyword in INSTITUTION_KEYWORDS)
    return has_degree or has_institution


def clean_education_line(line: str) -> str:
    """Clean a candidate line by removing section header prefixes."""
    cleaned = line.strip()
    cleaned = re.sub(r"^(?:education|academic background|academic qualifications|qualifications):\s*", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


def contains_institution(line: str) -> bool:
    """Check if a cleaned line contains any institution keywords."""
    lowered = line.lower()
    return any(keyword in lowered for keyword in INSTITUTION_KEYWORDS)


def contains_degree(line: str) -> bool:
    """Check if a cleaned line contains a degree pattern."""
    return DEGREE_RE.search(line) is not None


def group_lines_into_education_blocks(candidate_lines: list[str]) -> list[list[str]]:
    """Group consecutive candidate lines into blocks for single education records."""
    blocks: list[list[str]] = []
    current_block: list[str] = []

    for line in candidate_lines:
        line_stripped = line.strip()
        if not line_stripped:
            continue

        has_inst = contains_institution(line_stripped)
        has_deg = contains_degree(line_stripped)

        if current_block:
            curr_has_inst = any(contains_institution(block_line) for block_line in current_block)
            curr_has_deg = any(contains_degree(block_line) for block_line in current_block)

            # Start new block if there's a collision (duplicate inst or deg, or line contains both)
            if (has_inst and curr_has_inst) or (has_deg and curr_has_deg) or (has_inst and has_deg):
                blocks.append(current_block)
                current_block = [line_stripped]
                continue

        current_block.append(line_stripped)

    if current_block:
        blocks.append(current_block)

    return blocks


class ParsedEducationBlock:
    def __init__(
        self,
        *,
        institution: str,
        degree: str | None,
        field_of_study: str | None,
        country: str | None,
        start_year: int | None,
        end_year: int | None,
    ) -> None:
        self.institution = institution
        self.degree = degree
        self.field_of_study = field_of_study
        self.country = country
        self.start_year = start_year
        self.end_year = end_year
        
        # Determine international status
        is_intl = False
        if country is not None:
            is_intl = country.lower() not in LOCAL_COUNTRIES
        else:
            inst_lower = institution.lower()
            if "international" in inst_lower:
                is_intl = True
            elif not any(local_kw in inst_lower for local_kw in LOCAL_KEYWORDS):
                # If there are no local keywords, default to international
                is_intl = True
                
        self.is_international = is_intl
        
        # If international, normalize country to "Non-local jurisdiction" if not specified
        if self.is_international and self.country is None:
            self.country = "Non-local jurisdiction"


def parse_education_block(block_lines: list[str]) -> ParsedEducationBlock | None:
    """Parse a block of lines into a structured education record."""
    # Extract degree line-by-line to avoid matching bleeding into adjacent lines
    degree = None
    for line in block_lines:
        deg_match = extract_degree(line)
        if deg_match:
            degree = deg_match
            break

    block_text = " ".join(block_lines)
    
    # Extract years
    start_year, end_year = extract_years_from_text(block_text)

    # Split lines into parts for country and institution extraction
    parts: list[str] = []
    for line in block_lines:
        parts.extend(split_education_parts(line))

    # Extract country
    country = extract_country(parts)

    # Extract institution
    institution = extract_institution_from_parts(parts, degree)

    if institution is None:
        if degree is not None:
            institution = "Unknown Institution"
        else:
            return None

    return ParsedEducationBlock(
        institution=institution,
        degree=degree,
        field_of_study=extract_field_of_study(degree),
        country=country,
        start_year=start_year,
        end_year=end_year,
    )


def split_education_parts(line: str) -> list[str]:
    """Split a single line into parts by comma, dash, or pipe separators."""
    normalized = line.replace("–", "-").replace("—", "-")
    return [
        part.strip(" .")
        for part in re.split(r"\s+-\s+|,\s*|\s+\|\s+", normalized)
        if part.strip(" .")
    ]


def extract_years_from_text(text: str) -> tuple[int | None, int | None]:
    """Extract start and end years from a text block."""
    # Check for range indicator like "2018 - Present" or "2018 to Present" or "2018 - "
    range_match = re.search(
        r"\b((?:19|20)\d{2})\s*(?:-|\u2013|\u2014|to)\s*(?:Present|Current|Ongoing|Now|\s*$)",
        text,
        re.IGNORECASE
    )
    if range_match:
        return int(range_match.group(1)), None

    matches = YEAR_RE.findall(text)
    if not matches:
        return None, None

    years = sorted(int(y) for y in matches)
    if len(years) >= 2:
        return years[0], years[1]
    return None, years[0]


def extract_degree(text: str) -> str | None:
    """Extract the degree name from the text using DEGREE_RE."""
    match = DEGREE_RE.search(text)
    if match is None:
        return None

    return re.sub(r"\s+", " ", match.group(1)).strip()


def extract_institution_from_parts(parts: list[str], degree: str | None) -> str | None:
    """Extract the institution name from parts, with fallbacks."""
    # First pass: find explicit institution keywords
    for part in parts:
        lowered = part.lower()
        if any(keyword in lowered for keyword in INSTITUTION_KEYWORDS):
            return strip_years(part)

    # Second pass: fallback to first part that is not a degree and not a year
    for part in parts:
        part_clean = strip_years(part)
        if not part_clean:
            continue
        if DEGREE_RE.search(part_clean):
            continue
        if YEAR_RE.search(part_clean):
            continue
        if len(part_clean) < 3:
            continue
        return part_clean

    return None


def extract_field_of_study(degree: str | None) -> str | None:
    """Extract the field of study from a degree string."""
    if degree is None:
        return None

    # 1. Match 'in <Field>'
    in_match = re.search(r"\bin\s+([A-Za-z\s&/-]+)", degree, re.IGNORECASE)
    if in_match:
        return in_match.group(1).strip()

    # 2. Match 'of <Field>' (except when followed by science/arts/etc.)
    of_match = re.search(
        r"\bof\s+(?!science\b|arts\b|laws\b|philosophy\b|engineering\b|technology\b|business\b)([A-Za-z\s&/-]+)",
        degree,
        re.IGNORECASE
    )
    if of_match:
        return of_match.group(1).strip()

    # 3. Match prefix abbreviations followed by field
    prefix_match = re.match(
        r"^(?:BSc|MSc|PhD|MBA|BA|MA|B\.Sc\.|M\.Sc\.|Ph\.D\.|B\.A\.|M\.A\.|B\.S\.|M\.S\.)\s+([A-Za-z\s&/-]+)",
        degree,
        re.IGNORECASE
    )
    if prefix_match:
        return prefix_match.group(1).strip()

    return None


def extract_country(parts: list[str]) -> str | None:
    """Extract country name from parts using COUNTRY_HINTS."""
    for part in reversed(parts):
        lowered = part.lower()
        if lowered in COUNTRY_HINTS:
            return normalize_country(part)

    return None


def strip_years(value: str) -> str:
    """Strip 4-digit years from a string."""
    cleaned = YEAR_RE.sub("", value)
    return re.sub(r"\s+", " ", cleaned).strip(" ,-\u2013\u2014")


def normalize_country(value: str) -> str:
    """Normalize country name to a standard capitalized form."""
    normalized = value.strip()
    if normalized.lower() == "usa":
        return "United States"
    if normalized.lower() == "uk":
        return "United Kingdom"
    return normalized.title()
