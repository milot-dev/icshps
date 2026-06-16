from __future__ import annotations

from pathlib import Path
import re

from icshps.agents.extraction.employment_history_extractor import (
    extract_employment_history,
)
from icshps.agents.extraction.pdf_bounding_boxes import find_text_bounding_box
from icshps.agents.extraction.synthetic_profile_fallback import (
    build_synthetic_candidate_profile,
    should_use_synthetic_fallback,
)
from icshps.schemas import (
    CandidateProfile,
    ConfidenceBand,
    EmploymentRecord,
    ExtractedField,
    ExtractionError,
    SkillRecord,
    EvidenceRef,
)
from icshps.schemas.profile import CertificationRecord

EMAIL_RE = re.compile(
    r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
    re.IGNORECASE,
)
PHONE_RE = re.compile(
    r"(?<!\w)(?:\+?\d{1,3}[\s.-]?)?(?:\(?\d{2,4}\)?[\s.-]?)?"
    r"\d{3,4}[\s.-]?\d{3,4}(?!\w)"
)

SKILL_KEYWORDS = (
    ("Python", "programming_language"),
    ("JavaScript", "programming_language"),
    ("TypeScript", "programming_language"),
    ("SQL", "database"),
    ("FastAPI", "backend"),
    ("React", "frontend"),
    ("Docker", "devops"),
    ("Git", "devops"),
    ("LangGraph", "ai_framework"),
    ("Machine Learning", "machine_learning"),
)

HIGH_CONFIDENCE_MIN = 0.80
MEDIUM_CONFIDENCE_MIN = 0.60
LOW_EXTRACTION_CONFIDENCE_THRESHOLD = MEDIUM_CONFIDENCE_MIN

FULL_NAME_CONFIDENCE = 0.80
EMAIL_CONFIDENCE = 0.95
PHONE_CONFIDENCE = 0.85
EXPLICIT_LOCATION_CONFIDENCE = 0.70
INFERRED_LOCATION_CONFIDENCE = 0.60
SKILL_CONFIDENCE = 0.80
CERTIFICATION_CONFIDENCE = 0.75
MISSING_CONFIDENCE = 0.0

CONTACT_CONFIDENCE_WEIGHT = 0.70
SKILLS_CONFIDENCE_WEIGHT = 0.30
LOW_CONFIDENCE_REVIEW_FLAG = "Low extraction confidence; manual review recommended."
MISSING_EVIDENCE_REVIEW_FLAG = (
    "Some extracted fields are missing evidence; manual review recommended."
)


def extract_candidate_profile(
    resume_text: str,
    *,
    candidate_id: str,
    application_id: str,
    role_id: str,
    source_file: str | Path = "resume_text",
) -> CandidateProfile:
    normalized_text = normalize_resume_text(resume_text)
    source_path = Path(str(source_file))

    if should_use_synthetic_fallback(extracted_text=normalized_text):
        return build_synthetic_candidate_profile(
            candidate_id=candidate_id,
            application_id=application_id,
            role_id=role_id,
            source_file=source_file,
            reason="Resume extraction returned empty text.",
        )

    lines = normalized_text.splitlines()
    full_name = extract_full_name(lines, source_path)

    if should_use_synthetic_fallback(
        extracted_text=normalized_text,
        missing_required_fields=full_name.value is None,
    ):
        return build_synthetic_candidate_profile(
            candidate_id=candidate_id,
            application_id=application_id,
            role_id=role_id,
            source_file=source_file,
            reason="Required candidate name could not be extracted.",
        )

    email = extract_regex_field(EMAIL_RE, normalized_text, source_path, EMAIL_CONFIDENCE)
    phone = extract_regex_field(PHONE_RE, normalized_text, source_path, PHONE_CONFIDENCE)
    location = extract_location(lines, source_path)
    skills = extract_skills(normalized_text, source_path)
    certifications = extract_certifications(normalized_text, source_path)
    employment_history = extract_employment_history(
        lines,
        source_path,
        make_employment_evidence,
    )
    extraction_errors = build_extraction_errors(email=email, phone=phone)
    section_confidence = calculate_section_confidence(
        full_name=full_name,
        email=email,
        phone=phone,
        location=location,
        skills=skills,
        certifications=certifications,
        employment_history=employment_history,
    )
    extraction_confidence = calculate_profile_confidence(section_confidence)
    section_confidence_bands = calculate_section_confidence_bands(section_confidence)
    manual_review_flags = [error.message for error in extraction_errors]

    if extraction_confidence < LOW_EXTRACTION_CONFIDENCE_THRESHOLD:
        manual_review_flags.append(LOW_CONFIDENCE_REVIEW_FLAG)

    if has_extracted_values_missing_evidence(
        full_name=full_name,
        email=email,
        phone=phone,
        location=location,
        skills=skills,
        employment_history=employment_history,
    ):
        manual_review_flags.append(MISSING_EVIDENCE_REVIEW_FLAG)

    return CandidateProfile(
        candidate_id=candidate_id,
        application_id=application_id,
        role_id=role_id,
        source_file=str(source_file),
        full_name=full_name,
        email=email,
        phone=phone,
        location=location,
        skills=skills,
        certifications=certifications,
        employment_history=employment_history,
        education=[],
        total_years_experience_estimate=None,
        relevant_years_experience_estimate=None,
        extraction_confidence=extraction_confidence,
        extraction_confidence_band=confidence_band_for_score(extraction_confidence),
        section_confidence=section_confidence,
        section_confidence_bands=section_confidence_bands,
        evidence_index=build_evidence_index(
            full_name=full_name,
            email=email,
            phone=phone,
            location=location,
            skills=skills,
            certifications=certifications,
            employment_history=employment_history,
        ),
        manual_review_flags=manual_review_flags,
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


def extract_full_name(lines: list[str], source_path: Path) -> ExtractedField:
    for line in lines[:6]:
        if EMAIL_RE.search(line) or PHONE_RE.search(line):
            continue

        words = line.split()
        if 2 <= len(words) <= 4 and not any(char.isdigit() for char in line):
            return ExtractedField(
                value=line,
                confidence=FULL_NAME_CONFIDENCE,
                evidence=[
                    make_contact_evidence(
                        source_path,
                        "full_name",
                        line,
                        FULL_NAME_CONFIDENCE,
                    )
                ],
            )

    return ExtractedField(
        value=None,
        confidence=MISSING_CONFIDENCE,
        evidence=[],
    )


def extract_regex_field(
    pattern: re.Pattern[str],
    text: str,
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
        evidence=[
            make_contact_evidence(
                source_path,
                contact_field_for_pattern(pattern),
                value,
                confidence,
            )
        ],
    )


def extract_location(lines: list[str], source_path: Path) -> ExtractedField | None:
    for line in lines[:8]:
        lowered = line.lower()

        if lowered.startswith("location:"):
            value = line.split(":", 1)[1].strip()
            return ExtractedField(
                value=value,
                confidence=EXPLICIT_LOCATION_CONFIDENCE,
                evidence=[
                    make_contact_evidence(
                        source_path,
                        "location",
                        line,
                        EXPLICIT_LOCATION_CONFIDENCE,
                    )
                ],
            )

        if "," in line and not EMAIL_RE.search(line) and not PHONE_RE.search(line):
            return ExtractedField(
                value=line,
                confidence=INFERRED_LOCATION_CONFIDENCE,
                evidence=[
                    make_contact_evidence(
                        source_path,
                        "location",
                        line,
                        INFERRED_LOCATION_CONFIDENCE,
                    )
                ],
            )

    return None


def extract_skills(text: str, source_path: Path) -> list[SkillRecord]:
    skills = []

    for name, category in SKILL_KEYWORDS:
        pattern = r"(?<![A-Za-z0-9+#])" + re.escape(name) + r"(?![A-Za-z0-9+#])"
        if re.search(pattern, text, re.IGNORECASE):
            skill_index = len(skills)
            skills.append(
                SkillRecord(
                    name=name,
                    normalized_name=re.sub(r"\s+", "_", name.lower()),
                    category=category,
                    confidence=SKILL_CONFIDENCE,
                    evidence=[
                        make_skill_evidence(
                            source_path,
                            skill_index,
                            name,
                            SKILL_CONFIDENCE,
                        )
                    ],
                )
            )

    return skills


def extract_certifications(text: str, source_path: Path) -> list[CertificationRecord]:
    """Extract certifications from resume text into structured CertificationRecord list."""
    certs: list[CertificationRecord] = []

    # Simple heuristics: lines containing 'cert' or 'certificate' or 'certified'
    for line in text.splitlines():
        lowered = line.lower()
        if "cert" in lowered or "certificate" in lowered or "certified" in lowered:
            # try to parse name, issuer, year
            name = line.strip()
            issuer = None
            issued_date = None

            # split on ' - ' or ' by ' or ',' to try to find issuer
            if " - " in line:
                parts = [p.strip() for p in line.split(" - ", 1)]
                name = parts[0]
                issuer = parts[1] if len(parts) > 1 else None
            elif " by " in lowered:
                parts = re.split(r" by ", line, flags=re.IGNORECASE)
                name = parts[0].strip()
                issuer = parts[1].strip() if len(parts) > 1 else None
            else:
                # comma separated: Name, Issuer, Year
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 2:
                    name = parts[0]
                    issuer = parts[1]

            # detect a 4-digit year for issued_date
            year_match = re.search(r"(19|20)\d{2}", line)
            if year_match:
                issued_date = year_match.group(0)

            cert_index = len(certs)
            certs.append(
                CertificationRecord(
                    name=name,
                    issuer=issuer,
                    issued_date=issued_date,
                    confidence=CERTIFICATION_CONFIDENCE,
                    evidence=[
                        make_certification_evidence(
                            source_path,
                            cert_index,
                            line,
                            CERTIFICATION_CONFIDENCE,
                        )
                    ],
                )
            )

    return certs


def build_extraction_errors(
    *,
    email: ExtractedField | None,
    phone: ExtractedField | None,
) -> list[ExtractionError]:
    if email is not None or phone is not None:
        return []

    return [
        ExtractionError(
            code="MISSING_CONTACT_INFO",
            message="No email or phone number was detected.",
            severity="warning",
        )
    ]


def calculate_section_confidence(
    *,
    full_name: ExtractedField,
    email: ExtractedField | None,
    phone: ExtractedField | None,
    location: ExtractedField | None,
    skills: list[SkillRecord],
    certifications: list[CertificationRecord] | None = None,
    employment_history: list[EmploymentRecord] | None = None,
) -> dict[str, float]:
    return {
        "contact": average_confidence(
            [
                full_name.confidence,
                email.confidence if email else MISSING_CONFIDENCE,
                phone.confidence if phone else MISSING_CONFIDENCE,
                location.confidence if location else MISSING_CONFIDENCE,
            ]
        ),
        "skills": average_confidence([skill.confidence for skill in skills]),
        "employment_history": average_confidence(
            [record.confidence for record in employment_history]
            if employment_history
            else []
        ),
        "education": MISSING_CONFIDENCE,
        "certifications": average_confidence(
            [c.confidence for c in certifications] if certifications else []
        ),
    }


def calculate_profile_confidence(section_confidence: dict[str, float]) -> float:
    return round(
        (
            section_confidence.get("contact", 0.0) * CONTACT_CONFIDENCE_WEIGHT
            + section_confidence.get("skills", 0.0) * SKILLS_CONFIDENCE_WEIGHT
        ),
        2,
    )


def average_confidence(values: list[float]) -> float:
    if not values:
        return MISSING_CONFIDENCE

    return round(sum(values) / len(values), 2)


def calculate_section_confidence_bands(
    section_confidence: dict[str, float],
) -> dict[str, ConfidenceBand]:
    return {
        section: confidence_band_for_score(score)
        for section, score in section_confidence.items()
    }


def confidence_band_for_score(score: float) -> ConfidenceBand:
    if score >= HIGH_CONFIDENCE_MIN:
        return "high"

    if score >= MEDIUM_CONFIDENCE_MIN:
        return "medium"

    return "low"


def has_extracted_values_missing_evidence(
    *,
    full_name: ExtractedField,
    email: ExtractedField | None,
    phone: ExtractedField | None,
    location: ExtractedField | None,
    skills: list[SkillRecord],
    employment_history: list[EmploymentRecord] | None = None,
) -> bool:
    fields = [full_name, email, phone, location]

    for field in fields:
        if field and field.value and not field.evidence:
            return True

    if any(skill.name and not skill.evidence for skill in skills):
        return True

    return any(
        record.company and not record.evidence
        for record in employment_history or []
    )


def build_evidence_index(
    *,
    full_name: ExtractedField,
    email: ExtractedField | None,
    phone: ExtractedField | None,
    location: ExtractedField | None,
    skills: list[SkillRecord],
    certifications: list[CertificationRecord] | None = None,
    employment_history: list[EmploymentRecord] | None = None,
) -> list[EvidenceRef]:
    evidence_refs: list[EvidenceRef] = []

    for field in [full_name, email, phone, location]:
        if field:
            evidence_refs.extend(field.evidence)

    for skill in skills:
        evidence_refs.extend(skill.evidence)

    if employment_history:
        for employment_record in employment_history:
            evidence_refs.extend(employment_record.evidence)

    if certifications:
        for cert in certifications:
            evidence_refs.extend(cert.evidence)

    return dedupe_evidence_refs(evidence_refs)


def dedupe_evidence_refs(evidence_refs: list[EvidenceRef]) -> list[EvidenceRef]:
    deduped = []
    seen = set()

    for evidence in evidence_refs:
        key = evidence.evidence_id or (
            str(evidence.source_path),
            evidence.source_type,
            evidence.page_number,
            evidence.section,
            evidence.text_snippet,
        )
        if key in seen:
            continue

        seen.add(key)
        deduped.append(evidence)

    return deduped


def make_evidence(
    source_path: Path,
    section: str,
    snippet: str,
    confidence: float,
    *,
    evidence_id: str,
    field_path: str,
) -> EvidenceRef:
    normalized_snippet = re.sub(r"\s+", " ", snippet).strip()[:240]
    bounding_box_result = find_text_bounding_box(source_path, normalized_snippet)

    return EvidenceRef(
        evidence_id=evidence_id,
        field_path=field_path,
        source_path=source_path,
        source_type=source_type_for_path(source_path),
        page_number=bounding_box_result.page_number,
        section=section,
        text_snippet=normalized_snippet,
        confidence=confidence,
        extraction_method="regex_resume_text",
        bounding_box=bounding_box_result.bounding_box,
    )


def source_type_for_path(source_path: Path) -> str:
    if source_path.suffix.lower() == ".pdf":
        return "resume_pdf"

    return "resume_text"


def make_contact_evidence(
    source_path: Path,
    field_path: str,
    snippet: str,
    confidence: float,
) -> EvidenceRef:
    return make_evidence(
        source_path,
        "contact",
        snippet,
        confidence,
        evidence_id=f"ev_contact_{field_path}_001",
        field_path=field_path,
    )


def make_skill_evidence(
    source_path: Path,
    skill_index: int,
    skill_name: str,
    confidence: float,
) -> EvidenceRef:
    return make_evidence(
        source_path,
        "skills",
        skill_name,
        confidence,
        evidence_id=f"ev_skill_{slugify_evidence_component(skill_name)}_001",
        field_path=f"skills[{skill_index}]",
    )


def make_certification_evidence(
    source_path: Path,
    cert_index: int,
    snippet: str,
    confidence: float,
) -> EvidenceRef:
    return make_evidence(
        source_path,
        "certification",
        snippet,
        confidence,
        evidence_id=f"ev_certification_{cert_index}_name_001",
        field_path=f"certifications[{cert_index}].name",
    )


def make_employment_evidence(
    source_path: Path,
    record_index: int,
    snippet: str,
    confidence: float,
) -> EvidenceRef:
    return make_evidence(
        source_path,
        "employment_history",
        snippet,
        confidence,
        evidence_id=f"ev_employment_{record_index}_dates_001",
        field_path=f"employment_history[{record_index}]",
    )


def contact_field_for_pattern(pattern: re.Pattern[str]) -> str:
    if pattern is EMAIL_RE:
        return "email"

    if pattern is PHONE_RE:
        return "phone"

    return "contact"


def slugify_evidence_component(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return slug or "unknown"
