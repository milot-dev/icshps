from __future__ import annotations

from pathlib import Path
from typing import Any
import re

from icshps.agents.extraction.education_extractor import (
    extract_education_records,
)
from icshps.agents.extraction.employment_history_extractor import (
    extract_employment_history,
)
from icshps.agents.extraction.llm_recovery import (
    LLMRecoveryMetrics,
    LLMRecoveryProvider,
    apply_llm_recovery,
    llm_recovery_enabled,
)
from icshps.agents.extraction.pdf_bounding_boxes import find_text_bounding_box
from icshps.agents.extraction.synthetic_profile_fallback import (
    build_synthetic_candidate_profile,
    fallback_reason_for_trigger,
    should_use_synthetic_fallback,
)
from icshps.schemas import (
    CandidateProfile,
    ConfidenceBand,
    EducationRecord,
    EmploymentRecord,
    ExtractedField,
    ExtractionError,
    SkillRecord,
    EvidenceRef,
)
from icshps.schemas.profile import CertificationRecord
from icshps.utils.evidence import dedupe_evidence_refs
from icshps.utils.text import normalize_whitespace, slugify

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
EDUCATION_CONFIDENCE = 0.70
MISSING_CONFIDENCE = 0.0

CONTACT_CONFIDENCE_WEIGHT = 0.70
SKILLS_CONFIDENCE_WEIGHT = 0.30
LOW_CONFIDENCE_REVIEW_FLAG = "Low extraction confidence; manual review recommended."
VISION_OCR_CONFIDENCE_MULTIPLIER = 0.75
VISION_OCR_REVIEW_FLAG = "Vision-extracted resume text requires manual review."
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
    llm_provider: LLMRecoveryProvider | None = None,
    llm_metrics: dict[str, Any] | None = None,
    ocr_manual_review_required: bool = False,
) -> CandidateProfile:
    normalized_text = normalize_resume_text(resume_text)
    source_path = Path(str(source_file))
    ocr_requires_review = ocr_manual_review_required

    if should_use_synthetic_fallback(extracted_text=normalized_text):
        _record_llm_metrics(
            llm_metrics,
            LLMRecoveryMetrics(
                enabled=llm_recovery_enabled(),
                final_extraction_mode="synthetic_fallback",
                manual_review_flag_count=2,
                skipped_reason="resume_text_unusable",
            ),
        )
        trigger = (
            "resume_text_empty" if not normalized_text else "resume_text_too_short"
        )
        profile = build_synthetic_candidate_profile(
            candidate_id=candidate_id,
            application_id=application_id,
            role_id=role_id,
            source_file=source_file,
            reason=fallback_reason_for_trigger(trigger),
        )
        _append_ocr_review_flag(profile, ocr_requires_review)
        _update_manual_review_metric(llm_metrics, profile)
        return profile

    try:
        lines = normalized_text.splitlines()
        full_name = extract_full_name(lines, source_path)
        email = extract_regex_field(
            EMAIL_RE, normalized_text, source_path, EMAIL_CONFIDENCE
        )
        phone = extract_regex_field(
            PHONE_RE, normalized_text, source_path, PHONE_CONFIDENCE
        )
        location = extract_location(lines, source_path)
        skills = extract_skills(normalized_text, source_path)
        certifications = extract_certifications(normalized_text, source_path)
        education = extract_education_records(
            lines,
            source_path,
            make_education_evidence,
        )
        employment_history = extract_employment_history(
            lines,
            source_path,
            make_employment_evidence,
        )
        ocr_confidence_multiplier = _ocr_confidence_multiplier(
            vision_ocr_used=ocr_manual_review_required,
        )
        if ocr_confidence_multiplier is not None:
            full_name = _penalize_ocr_confidence(
                full_name, ocr_confidence_multiplier, "regex_resume_llm_vision"
            )
            email = _penalize_optional_ocr_confidence(
                email, ocr_confidence_multiplier, "regex_resume_llm_vision"
            )
            phone = _penalize_optional_ocr_confidence(
                phone, ocr_confidence_multiplier, "regex_resume_llm_vision"
            )
            location = _penalize_optional_ocr_confidence(
                location, ocr_confidence_multiplier, "regex_resume_llm_vision"
            )
            skills = _penalize_ocr_records(
                skills, ocr_confidence_multiplier, "regex_resume_llm_vision"
            )
            certifications = _penalize_ocr_records(
                certifications, ocr_confidence_multiplier, "regex_resume_llm_vision"
            )
            education = _penalize_ocr_records(
                education, ocr_confidence_multiplier, "regex_resume_llm_vision"
            )
            employment_history = _penalize_ocr_records(
                employment_history,
                ocr_confidence_multiplier,
                "regex_resume_llm_vision",
            )
        extraction_errors = build_extraction_errors(email=email, phone=phone)
        section_confidence = calculate_section_confidence(
            full_name=full_name,
            email=email,
            phone=phone,
            location=location,
            skills=skills,
            certifications=certifications,
            education=education,
            employment_history=employment_history,
        )
        extraction_confidence = calculate_profile_confidence(section_confidence)
        section_confidence_bands = calculate_section_confidence_bands(
            section_confidence
        )

        llm_recovery = apply_llm_recovery(
            resume_text=normalized_text,
            source_path=source_path,
            full_name=full_name,
            email=email,
            phone=phone,
            location=location,
            skills=skills,
            employment_history=employment_history,
            education=education,
            certifications=certifications,
            extraction_confidence=extraction_confidence,
            section_confidence=section_confidence,
            provider=llm_provider,
        )
        _record_llm_metrics(llm_metrics, llm_recovery.metrics)

        full_name = llm_recovery.full_name
        email = llm_recovery.email
        phone = llm_recovery.phone
        location = llm_recovery.location
        skills = llm_recovery.skills
        employment_history = llm_recovery.employment_history
        education = llm_recovery.education
        certifications = llm_recovery.certifications

        if ocr_confidence_multiplier is not None:
            full_name = _penalize_ocr_confidence(
                full_name, ocr_confidence_multiplier, "llm_recovery_vision"
            )
            email = _penalize_optional_ocr_confidence(
                email, ocr_confidence_multiplier, "llm_recovery_vision"
            )
            phone = _penalize_optional_ocr_confidence(
                phone, ocr_confidence_multiplier, "llm_recovery_vision"
            )
            location = _penalize_optional_ocr_confidence(
                location, ocr_confidence_multiplier, "llm_recovery_vision"
            )
            skills = _penalize_ocr_records(
                skills, ocr_confidence_multiplier, "llm_recovery_vision"
            )
            certifications = _penalize_ocr_records(
                certifications, ocr_confidence_multiplier, "llm_recovery_vision"
            )
            education = _penalize_ocr_records(
                education, ocr_confidence_multiplier, "llm_recovery_vision"
            )
            employment_history = _penalize_ocr_records(
                employment_history, ocr_confidence_multiplier, "llm_recovery_vision"
            )

        if should_use_synthetic_fallback(
            extracted_text=normalized_text,
            missing_required_fields=full_name.value is None,
        ):
            llm_recovery.metrics.final_extraction_mode = "synthetic_fallback"
            llm_recovery.metrics.manual_review_flag_count = 2
            _record_llm_metrics(llm_metrics, llm_recovery.metrics)
            profile = build_synthetic_candidate_profile(
                candidate_id=candidate_id,
                application_id=application_id,
                role_id=role_id,
                source_file=source_file,
                reason=fallback_reason_for_trigger("missing_required_profile_fields"),
            )
            _append_ocr_review_flag(profile, ocr_requires_review)
            _update_manual_review_metric(llm_metrics, profile)
            return profile

        extraction_errors = build_extraction_errors(email=email, phone=phone)
        section_confidence = calculate_section_confidence(
            full_name=full_name,
            email=email,
            phone=phone,
            location=location,
            skills=skills,
            certifications=certifications,
            education=education,
            employment_history=employment_history,
        )
        extraction_confidence = calculate_profile_confidence(section_confidence)
        section_confidence_bands = calculate_section_confidence_bands(
            section_confidence
        )
        manual_review_flags = [
            *[error.message for error in extraction_errors],
            *llm_recovery.manual_review_flags,
        ]
    except Exception as exc:
        _record_llm_metrics(
            llm_metrics,
            LLMRecoveryMetrics(
                enabled=llm_recovery_enabled(),
                final_extraction_mode="synthetic_fallback",
                manual_review_flag_count=2,
                skipped_reason="deterministic_extraction_failed",
            ),
        )
        profile = build_synthetic_candidate_profile(
            candidate_id=candidate_id,
            application_id=application_id,
            role_id=role_id,
            source_file=source_file,
            reason=f"{fallback_reason_for_trigger('profile_extraction_failed')} {exc}",
        )
        _append_ocr_review_flag(profile, ocr_requires_review)
        _update_manual_review_metric(llm_metrics, profile)
        return profile

    if extraction_confidence < LOW_EXTRACTION_CONFIDENCE_THRESHOLD:
        manual_review_flags.append(LOW_CONFIDENCE_REVIEW_FLAG)

    if ocr_requires_review:
        manual_review_flags.append(VISION_OCR_REVIEW_FLAG)

    if has_extracted_values_missing_evidence(
        full_name=full_name,
        email=email,
        phone=phone,
        location=location,
        skills=skills,
        education=education,
        employment_history=employment_history,
    ):
        manual_review_flags.append(MISSING_EVIDENCE_REVIEW_FLAG)

    if llm_metrics is not None:
        llm_metrics["manual_review_flag_count"] = len(manual_review_flags)

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
        education=education,
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
            education=education,
            employment_history=employment_history,
        ),
        manual_review_flags=manual_review_flags,
        synthetic_fallback_used=False,
        extraction_errors=extraction_errors,
    )


def _ocr_confidence_multiplier(
    *,
    vision_ocr_used: bool = False,
) -> float | None:
    if vision_ocr_used:
        return VISION_OCR_CONFIDENCE_MULTIPLIER
    return None


def _penalize_optional_ocr_confidence(
    record: Any | None,
    multiplier: float,
    extraction_method: str,
) -> Any | None:
    if record is None:
        return None
    return _penalize_ocr_confidence(record, multiplier, extraction_method)


def _penalize_ocr_records(
    records: list[Any],
    multiplier: float,
    extraction_method: str,
) -> list[Any]:
    return [
        _penalize_ocr_confidence(record, multiplier, extraction_method)
        for record in records
    ]


def _penalize_ocr_confidence(
    record: Any,
    multiplier: float,
    extraction_method: str,
) -> Any:
    matching_evidence = [
        evidence
        for evidence in record.evidence
        if evidence.extraction_method == extraction_method
    ]
    if not matching_evidence:
        return record

    updated_evidence = [
        evidence.model_copy(
            update={"confidence": _reduced_confidence(evidence.confidence, multiplier)}
        )
        if evidence.extraction_method == extraction_method
        else evidence
        for evidence in record.evidence
    ]
    return record.model_copy(
        update={
            "confidence": _reduced_confidence(record.confidence, multiplier),
            "evidence": updated_evidence,
        }
    )


def _reduced_confidence(confidence: float | None, multiplier: float) -> float | None:
    if confidence is None:
        return None
    return round(confidence * multiplier, 3)


def _append_ocr_review_flag(
    profile: CandidateProfile,
    ocr_requires_review: bool,
) -> None:
    if (
        ocr_requires_review
        and VISION_OCR_REVIEW_FLAG not in profile.manual_review_flags
    ):
        profile.manual_review_flags.append(VISION_OCR_REVIEW_FLAG)


def _update_manual_review_metric(
    llm_metrics: dict[str, Any] | None,
    profile: CandidateProfile,
) -> None:
    if llm_metrics is not None:
        llm_metrics["manual_review_flag_count"] = len(profile.manual_review_flags)


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
    education: list[EducationRecord] | None = None,
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
        "education": average_confidence(
            [record.confidence for record in education] if education else []
        ),
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
    education: list[EducationRecord] | None = None,
    employment_history: list[EmploymentRecord] | None = None,
) -> bool:
    fields = [full_name, email, phone, location]

    for field in fields:
        if field and field.value and not field.evidence:
            return True

    if any(skill.name and not skill.evidence for skill in skills):
        return True

    if any(record.institution and not record.evidence for record in education or []):
        return True

    return any(
        record.company and not record.evidence for record in employment_history or []
    )


def build_evidence_index(
    *,
    full_name: ExtractedField,
    email: ExtractedField | None,
    phone: ExtractedField | None,
    location: ExtractedField | None,
    skills: list[SkillRecord],
    certifications: list[CertificationRecord] | None = None,
    education: list[EducationRecord] | None = None,
    employment_history: list[EmploymentRecord] | None = None,
) -> list[EvidenceRef]:
    evidence_refs: list[EvidenceRef] = []

    for field in [full_name, email, phone, location]:
        if field:
            evidence_refs.extend(field.evidence)

    for skill in skills:
        evidence_refs.extend(skill.evidence)

    if education:
        for education_record in education:
            evidence_refs.extend(education_record.evidence)

    if employment_history:
        for employment_record in employment_history:
            evidence_refs.extend(employment_record.evidence)

    if certifications:
        for cert in certifications:
            evidence_refs.extend(cert.evidence)

    return dedupe_evidence_refs(evidence_refs)


def make_evidence(
    source_path: Path,
    section: str,
    snippet: str,
    confidence: float,
    *,
    evidence_id: str,
    field_path: str,
) -> EvidenceRef:
    normalized_snippet = normalize_whitespace(snippet)[:240]
    bounding_box_result = find_text_bounding_box(source_path, normalized_snippet)

    extraction_method = (
        "regex_resume_llm_vision"
        if bounding_box_result.source_method == "llm_vision_ocr"
        else "regex_resume_text"
    )

    return EvidenceRef(
        evidence_id=evidence_id,
        field_path=field_path,
        source_path=source_path,
        source_type=source_type_for_path(source_path),
        page_number=bounding_box_result.page_number,
        section=section,
        text_snippet=normalized_snippet,
        confidence=confidence,
        extraction_method=extraction_method,
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
        evidence_id=f"ev_skill_{slugify(skill_name)}_001",
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


def make_education_evidence(
    source_path: Path,
    education_index: int,
    snippet: str,
    confidence: float,
) -> EvidenceRef:
    return make_evidence(
        source_path,
        "education",
        snippet,
        confidence,
        evidence_id=f"ev_education_{education_index}_record_001",
        field_path=f"education[{education_index}]",
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


def _record_llm_metrics(
    metrics_payload: dict[str, Any] | None,
    metrics: LLMRecoveryMetrics,
) -> None:
    if metrics_payload is not None:
        metrics_payload.clear()
        metrics_payload.update(metrics.as_dict())
