from __future__ import annotations

from pathlib import Path
import re

from icshps.schemas.common import EvidenceRef
from icshps.schemas.profile import (
    CandidateProfile,
    CertificationRecord,
    EducationRecord,
    EmploymentRecord,
    ExtractedField,
    ExtractionError,
    SkillRecord,
)


EMAIL_RE = re.compile(
    r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
PHONE_RE = re.compile(
    r"(?<!\w)(?:\+?\d{1,3}[\s.-]?)?(?:\(?\d{2,4}\)?[\s.-]?)?\d{3,4}[\s.-]?\d{3,4}(?!\w)"
)
LINKEDIN_RE = re.compile(
    r"(?:https?://)?(?:www\.)?linkedin\.com/in/[A-Za-z0-9_.%-]+/?",
    re.IGNORECASE,
)

YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")
DATE_RANGE_RE = re.compile(
    r"(?P<start>(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)?\.?\s*\d{4}|\d{4})"
    r"\s*(?:-|–|—|to)\s*"
    r"(?P<end>Present|Current|Now|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)?\.?\s*\d{4}|\d{4})",
    re.IGNORECASE,
)

SECTION_HEADINGS = {
    "skills": {"skills", "technical skills", "core skills", "technologies"},
    "education": {"education", "academic background"},
    "certifications": {"certifications", "certification", "certificates", "licenses", "licences"},
    "employment_history": {
        "experience",
        "work experience",
        "professional experience",
        "employment history",
        "work history",
    },
}

SKILL_KEYWORDS = (
    ("Python", "programming_language"),
    ("Java", "programming_language"),
    ("JavaScript", "programming_language"),
    ("TypeScript", "programming_language"),
    ("SQL", "database"),
    ("PostgreSQL", "database"),
    ("MySQL", "database"),
    ("Pandas", "data"),
    ("NumPy", "data"),
    ("Scikit-learn", "machine_learning"),
    ("TensorFlow", "machine_learning"),
    ("PyTorch", "machine_learning"),
    ("LangChain", "ai_framework"),
    ("LangGraph", "ai_framework"),
    ("FastAPI", "backend"),
    ("Django", "backend"),
    ("React", "frontend"),
    ("Docker", "devops"),
    ("Git", "devops"),
    ("AWS", "cloud"),
    ("Azure", "cloud"),
    ("Machine Learning", "machine_learning"),
    ("Deep Learning", "machine_learning"),
    ("NLP", "machine_learning"),
    ("RAG", "ai_framework"),
)


def extract_candidate_profile(
    resume_text: str,
    *,
    candidate_id: str,
    application_id: str,
    role_id: str,
    source_file: str | Path = "resume_text",
) -> CandidateProfile:
    normalized = normalize_resume_text(resume_text)
    lines = [line for line in normalized.split("\n") if line.strip()]
    sections = split_sections(lines)
    source_path = Path(str(source_file))

    full_name = extract_full_name(lines, source_path)
    email = extract_regex_field(
        EMAIL_RE, normalized, "contact", source_path, 0.95)
    phone = extract_regex_field(
        PHONE_RE, normalized, "contact", source_path, 0.85)
    linkedin_url = extract_regex_field(
        LINKEDIN_RE, normalized, "contact", source_path, 0.9)
    location = extract_location(lines, source_path)

    skills = extract_skills(normalized, source_path)
    education = extract_education(sections.get("education", []), source_path)
    certifications = extract_certifications(
        sections.get("certifications", []), source_path)
    employment_history = extract_employment_history(
        sections.get("employment_history", []),
        source_path,
    )

    extraction_errors = build_errors(
        full_name=full_name,
        email=email,
        phone=phone,
        education=education,
        employment_history=employment_history,
    )

    section_confidence = {
        "contact": avg([
            full_name.confidence,
            email.confidence if email else 0.0,
            phone.confidence if phone else 0.0,
            location.confidence if location else 0.0,
            linkedin_url.confidence if linkedin_url else 0.0,
        ]),
        "skills": 0.9 if skills else 0.0,
        "employment_history": 0.8 if employment_history else 0.0,
        "education": 0.8 if education else 0.0,
        "certifications": 0.8 if certifications else 0.5,
    }

    return CandidateProfile(
        candidate_id=candidate_id,
        application_id=application_id,
        role_id=role_id,
        source_file=str(source_file),
        full_name=full_name,
        email=email,
        phone=phone,
        location=location,
        linkedin_url=linkedin_url,
        skills=skills,
        employment_history=employment_history,
        education=education,
        certifications=certifications,
        total_years_experience_estimate=estimate_years(employment_history),
        relevant_years_experience_estimate=estimate_years(employment_history),
        extraction_confidence=round(avg(section_confidence.values()), 2),
        section_confidence={
            key: round(value, 2)
            for key, value in section_confidence.items()
        },
        evidence_index=build_evidence_index(sections, source_path),
        manual_review_flags=[
            error.message
            for error in extraction_errors
            if error.severity in {"warning", "error"}
        ],
        synthetic_fallback_used=False,
        extraction_errors=extraction_errors,
    )


def normalize_resume_text(text: str) -> str:
    if not text:
        return ""

    text = text.replace("\x00", "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    lines = []
    for line in text.split("\n"):
        cleaned = re.sub(r"[ \t\f\v]+", " ", line).strip()
        if cleaned:
            lines.append(cleaned)

    return "\n".join(lines)


def split_sections(lines: list[str]) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {"header": []}
    current = "header"

    for line in lines:
        section = canonical_section(line)
        if section:
            current = section
            sections.setdefault(current, [])
            continue

        sections.setdefault(current, []).append(line)

    return sections


def canonical_section(line: str) -> str | None:
    normalized = re.sub(r"[^a-zA-Z ]+", "", line).strip().lower()

    if len(normalized.split()) > 4:
        return None

    for section_name, aliases in SECTION_HEADINGS.items():
        if normalized in aliases:
            return section_name

    return None


def extract_full_name(lines: list[str], source_path: Path) -> ExtractedField:
    for line in lines[:8]:
        if EMAIL_RE.search(line) or PHONE_RE.search(line) or LINKEDIN_RE.search(line):
            continue

        if canonical_section(line):
            continue

        words = line.split()
        if 2 <= len(words) <= 4 and not any(char.isdigit() for char in line):
            if all(word[:1].isupper() for word in words if word[:1].isalpha()):
                return ExtractedField(
                    value=line,
                    confidence=0.85,
                    evidence=[make_evidence(
                        source_path, "contact", line, 0.85)],
                )

    return ExtractedField(value=None, confidence=0.0, evidence=[])


def extract_regex_field(
    pattern: re.Pattern[str],
    text: str,
    section: str,
    source_path: Path,
    confidence: float,
) -> ExtractedField | None:
    match = pattern.search(text)

    if not match:
        return None

    value = match.group(0).strip()

    return ExtractedField(
        value=value,
        confidence=confidence,
        evidence=[make_evidence(source_path, section, value, confidence)],
    )


def extract_location(lines: list[str], source_path: Path) -> ExtractedField | None:
    location_hints = [
        "kosovo",
        "prishtina",
        "pristina",
        "albania",
        "tirana",
        "remote",
        "germany",
        "berlin",
        "usa",
        "united states",
        "united kingdom",
        "london",
    ]

    for line in lines[:12]:
        lowered = line.lower()

        if lowered.startswith(("location:", "address:")):
            value = line.split(":", 1)[1].strip()
            return ExtractedField(
                value=value,
                confidence=0.75,
                evidence=[make_evidence(source_path, "contact", line, 0.75)],
            )

        if any(hint in lowered for hint in location_hints) and not EMAIL_RE.search(line):
            return ExtractedField(
                value=line,
                confidence=0.65,
                evidence=[make_evidence(source_path, "contact", line, 0.65)],
            )

    return None


def extract_skills(text: str, source_path: Path) -> list[SkillRecord]:
    skills = []

    for name, category in SKILL_KEYWORDS:
        pattern = r"(?<![A-Za-z0-9+#])" + \
            re.escape(name) + r"(?![A-Za-z0-9+#])"

        if re.search(pattern, text, re.IGNORECASE):
            skills.append(
                SkillRecord(
                    name=name,
                    normalized_name=re.sub(r"\s+", "_", name.lower()),
                    category=category,
                    confidence=0.9,
                    evidence=[make_evidence(source_path, "skills", name, 0.9)],
                )
            )

    return skills


def extract_education(lines: list[str], source_path: Path) -> list[EducationRecord]:
    records = []

    for line in clean_lines(lines):
        lowered = line.lower()

        if not any(word in lowered for word in ["university", "college", "bachelor", "master", "degree", "phd", "diploma"]):
            continue

        years = [int(year) for year in YEAR_RE.findall(line)]
        degree = extract_degree(line)

        records.append(
            EducationRecord(
                institution=extract_institution(line) or line,
                degree=degree,
                field_of_study=extract_field_of_study(line),
                country=extract_country(line),
                start_year=years[0] if len(years) >= 2 else None,
                end_year=years[-1] if years else None,
                is_international=False,
                verification_status=None,
                confidence=0.8,
                evidence=[make_evidence(source_path, "education", line, 0.8)],
            )
        )

    return records


def extract_certifications(lines: list[str], source_path: Path) -> list[CertificationRecord]:
    records = []

    for line in clean_lines(lines):
        years = YEAR_RE.findall(line)
        name = re.sub(
            r"\b(issued|expires|valid until)\b.*$",
            "",
            line,
            flags=re.IGNORECASE,
        ).strip(" -–—,;")

        if not name:
            continue

        records.append(
            CertificationRecord(
                name=name,
                issuer=extract_issuer(line),
                issued_date=years[0] if years else None,
                expiration_date=years[-1] if len(years) >= 2 else None,
                credential_id=extract_credential_id(line),
                verification_status=None,
                confidence=0.8,
                evidence=[make_evidence(
                    source_path, "certifications", line, 0.8)],
            )
        )

    return records


def extract_employment_history(lines: list[str], source_path: Path) -> list[EmploymentRecord]:
    records = []
    current: EmploymentRecord | None = None

    for raw_line in lines:
        line = clean_bullet(raw_line)
        date_match = DATE_RANGE_RE.search(line)

        if date_match:
            prefix = line[:date_match.start()].strip(" -–—,|")
            title, company = extract_title_company(prefix)
            end_value = date_match.group("end")
            is_current = end_value.lower() in {"present", "current", "now"}

            current = EmploymentRecord(
                company=company or "Unknown Company",
                title=title,
                start_date=normalize_date(date_match.group("start")),
                end_date=None if is_current else normalize_date(end_value),
                is_current=is_current,
                responsibilities=[],
                confidence=0.75,
                evidence=[make_evidence(
                    source_path, "employment_history", line, 0.75)],
            )

            records.append(current)
            continue

        if current is not None and raw_line.strip().startswith(("-", "•", "*")):
            current.responsibilities.append(line)

    return records


def extract_title_company(prefix: str) -> tuple[str | None, str | None]:
    for separator in [" at ", " @ ", " - ", " – ", " — ", " | "]:
        if separator in prefix:
            left, right = prefix.split(separator, 1)
            return left.strip() or None, right.strip() or None

    return prefix or None, None


def build_errors(
    *,
    full_name: ExtractedField,
    email: ExtractedField | None,
    phone: ExtractedField | None,
    education: list[EducationRecord],
    employment_history: list[EmploymentRecord],
) -> list[ExtractionError]:
    errors = []

    if not full_name.value:
        errors.append(
            ExtractionError(
                code="LOW_CONFIDENCE_FIELD",
                message="Full name could not be detected with baseline rules.",
                field_name="full_name",
                severity="warning",
            )
        )

    if email is None and phone is None:
        errors.append(
            ExtractionError(
                code="MISSING_CONTACT_INFO",
                message="No email or phone number was detected.",
                severity="warning",
            )
        )

    if not education:
        errors.append(
            ExtractionError(
                code="MISSING_EDUCATION",
                message="Education section was missing or could not be parsed.",
                severity="warning",
            )
        )

    if not employment_history:
        errors.append(
            ExtractionError(
                code="MISSING_EMPLOYMENT_HISTORY",
                message="Employment history section was missing or could not be parsed.",
                severity="warning",
            )
        )

    return errors


def build_evidence_index(sections: dict[str, list[str]], source_path: Path) -> list[EvidenceRef]:
    evidence = []

    for section_name in sorted(sections):
        text = "\n".join(sections[section_name]).strip()

        if text:
            evidence.append(
                make_evidence(
                    source_path,
                    section_name,
                    text[:240],
                    0.8,
                )
            )

    return evidence


def make_evidence(
    source_path: Path,
    section: str,
    snippet: str,
    confidence: float,
) -> EvidenceRef:
    return EvidenceRef(
        source_path=source_path,
        source_type="resume_text",
        section=section,
        text_snippet=re.sub(r"\s+", " ", snippet).strip()[:240],
        confidence=confidence,
    )


def clean_lines(lines: list[str]) -> list[str]:
    return [clean_bullet(line) for line in lines if clean_bullet(line)]


def clean_bullet(line: str) -> str:
    return re.sub(r"^[-•*]\s*", "", line).strip()


def extract_degree(line: str) -> str | None:
    for degree in ["Bachelor", "Master", "PhD", "Doctorate", "BSc", "MSc", "BA", "MA", "Diploma"]:
        if re.search(r"\b" + re.escape(degree) + r"\b", line, re.IGNORECASE):
            return degree

    return None


def extract_institution(line: str) -> str | None:
    parts = re.split(r"\s[-–—|,]\s", line)

    for part in parts:
        if any(word in part.lower() for word in ["university", "college", "school", "institute", "academy"]):
            return part.strip()

    return None


def extract_field_of_study(line: str) -> str | None:
    match = re.search(
        r"(?:in|of)\s+([A-Za-z ]{3,})(?:,|\||-|–|—|\d|$)",
        line,
        re.IGNORECASE,
    )

    return match.group(1).strip() if match else None


def extract_country(line: str) -> str | None:
    for country in ["Kosovo", "Albania", "Germany", "United Kingdom", "United States"]:
        if country.lower() in line.lower():
            return country

    return None


def extract_issuer(line: str) -> str | None:
    match = re.search(
        r"\b(?:by|from|issuer:)\s+([^,;|]+)", line, re.IGNORECASE)
    return match.group(1).strip() if match else None


def extract_credential_id(line: str) -> str | None:
    match = re.search(
        r"\b(?:credential id|id|license no\.?):\s*([A-Za-z0-9-]+)",
        line,
        re.IGNORECASE,
    )

    return match.group(1).strip() if match else None


def normalize_date(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace(".", "")).strip()


def estimate_years(records: list[EmploymentRecord]) -> float | None:
    if not records:
        return None

    total = 0.0

    for record in records:
        start_year = first_year(record.start_date)
        end_year = 2026 if record.is_current else first_year(record.end_date)

        if start_year and end_year and end_year >= start_year:
            total += max(end_year - start_year, 0.5)

    return round(total, 1) if total else None


def first_year(value: str | None) -> int | None:
    if not value:
        return None

    match = YEAR_RE.search(value)
    return int(match.group(1)) if match else None


def avg(values) -> float:
    values = list(values)
    return sum(values) / len(values) if values else 0.0
