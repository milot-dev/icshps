from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from pydantic import Field

from icshps.schemas.common import EvidenceRef, ICSHPSBaseModel
from icshps.schemas.profile import (
    CertificationRecord,
    EducationRecord,
    EmploymentRecord,
    ExtractedField,
    SkillRecord,
)
from icshps.utils.text import normalize_whitespace, slugify

LLM_EXTRACTION_ENABLED_ENV = "ICSHPS_LLM_EXTRACTION_ENABLED"
LLM_EXTRACTION_MODEL_ENV = "ICSHPS_LLM_EXTRACTION_MODEL"
LLM_EXTRACTION_MAX_TOKENS_ENV = "ICSHPS_LLM_EXTRACTION_MAX_TOKENS"
OPENAI_API_KEY_ENV = "OPENAI_API_KEY"
DEFAULT_LLM_EXTRACTION_MODEL = "gpt-5.4-mini"
DEFAULT_LLM_EXTRACTION_MAX_TOKENS = 1200

LLM_RECOVERY_CONFIDENCE = 0.68
RECOMMENDATION_TERMS = (
    "hire",
    "reject",
    "qualified",
    "unqualified",
    "good",
    "bad",
    "advance",
    "shortlist",
    "recommend",
    "ranking",
    "routing",
    "pass",
    "fail",
)

class LLMExtractedField(ICSHPSBaseModel):
    value: str | None = None
    source_snippet: str
    confidence: float = Field(default=LLM_RECOVERY_CONFIDENCE, ge=0.0, le=1.0)


class LLMSkill(ICSHPSBaseModel):
    name: str
    normalized_name: str | None = None
    category: str | None = None
    source_snippet: str
    confidence: float = Field(default=LLM_RECOVERY_CONFIDENCE, ge=0.0, le=1.0)


class LLMEmployment(ICSHPSBaseModel):
    company: str
    title: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    is_current: bool = False
    responsibilities: list[str] = Field(default_factory=list)
    source_snippet: str
    confidence: float = Field(default=LLM_RECOVERY_CONFIDENCE, ge=0.0, le=1.0)


class LLMEducation(ICSHPSBaseModel):
    institution: str
    degree: str | None = None
    field_of_study: str | None = None
    country: str | None = None
    start_year: int | None = None
    end_year: int | None = None
    is_international: bool = False
    verification_status: str | None = None
    source_snippet: str
    confidence: float = Field(default=LLM_RECOVERY_CONFIDENCE, ge=0.0, le=1.0)


class LLMCertification(ICSHPSBaseModel):
    name: str
    issuer: str | None = None
    issued_date: str | None = None
    expiration_date: str | None = None
    credential_id: str | None = None
    verification_status: str | None = None
    source_snippet: str
    confidence: float = Field(default=LLM_RECOVERY_CONFIDENCE, ge=0.0, le=1.0)


class LLMRejectedItem(ICSHPSBaseModel):
    field_path: str | None = None
    reason: str
    source_snippet: str | None = None


class LLMExtractionRecovery(ICSHPSBaseModel):
    full_name: LLMExtractedField | None = None
    email: LLMExtractedField | None = None
    phone: LLMExtractedField | None = None
    location: LLMExtractedField | None = None
    skills: list[LLMSkill] = Field(default_factory=list)
    employment_history: list[LLMEmployment] = Field(default_factory=list)
    education: list[LLMEducation] = Field(default_factory=list)
    certifications: list[LLMCertification] = Field(default_factory=list)
    rejected_items: list[LLMRejectedItem] = Field(default_factory=list)


class LLMRecoveryProvider(Protocol):
    def recover(self, *, resume_text: str, trigger_reasons: list[str]) -> LLMExtractionRecovery:
        """Return strict extraction recovery output from a provider."""


@dataclass
class LLMRecoveryMetrics:
    enabled: bool = False
    available: bool = False
    called: bool = False
    trigger_reasons: list[str] = field(default_factory=list)
    accepted_field_count: int = 0
    rejected_field_count: int = 0
    validation_error_count: int = 0
    recommendation_violation_count: int = 0
    skipped_reason: str | None = None
    final_extraction_mode: str = "deterministic"
    manual_review_flag_count: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "available": self.available,
            "called": self.called,
            "trigger_reasons": sorted(set(self.trigger_reasons)),
            "accepted_field_count": self.accepted_field_count,
            "rejected_field_count": self.rejected_field_count,
            "validation_error_count": self.validation_error_count,
            "recommendation_violation_count": self.recommendation_violation_count,
            "skipped_reason": self.skipped_reason,
            "final_extraction_mode": self.final_extraction_mode,
            "manual_review_flag_count": self.manual_review_flag_count,
        }


@dataclass
class LLMRecoveryResult:
    full_name: ExtractedField
    email: ExtractedField | None
    phone: ExtractedField | None
    location: ExtractedField | None
    skills: list[SkillRecord]
    employment_history: list[EmploymentRecord]
    education: list[EducationRecord]
    certifications: list[CertificationRecord]
    manual_review_flags: list[str]
    metrics: LLMRecoveryMetrics


class LangChainOpenAIRecoveryProvider:
    def __init__(self, *, model: str | None = None, max_tokens: int | None = None) -> None:
        self.model = model or os.getenv(
            LLM_EXTRACTION_MODEL_ENV,
            DEFAULT_LLM_EXTRACTION_MODEL,
        )
        self.max_tokens = max_tokens or llm_recovery_max_tokens()

    def recover(self, *, resume_text: str, trigger_reasons: list[str]) -> LLMExtractionRecovery:
        try:
            from langchain_core.messages import HumanMessage, SystemMessage
            from langchain_openai import ChatOpenAI
        except ImportError as exc:
            raise RuntimeError("LangChain OpenAI provider is not installed.") from exc

        model = ChatOpenAI(
            model=self.model,
            temperature=0,
            max_tokens=self.max_tokens,
        )
        structured_model = model.with_structured_output(LLMExtractionRecovery)
        response = structured_model.invoke(
            [
                SystemMessage(content=_system_prompt()),
                HumanMessage(
                    content=_human_prompt(
                        resume_text=resume_text,
                        trigger_reasons=trigger_reasons,
                    )
                ),
            ]
        )

        if isinstance(response, LLMExtractionRecovery):
            return response

        return LLMExtractionRecovery.model_validate(response)


def apply_llm_recovery(
    *,
    resume_text: str,
    source_path: Path,
    full_name: ExtractedField,
    email: ExtractedField | None,
    phone: ExtractedField | None,
    location: ExtractedField | None,
    skills: list[SkillRecord],
    employment_history: list[EmploymentRecord],
    education: list[EducationRecord],
    certifications: list[CertificationRecord],
    extraction_confidence: float,
    section_confidence: dict[str, float],
    provider: LLMRecoveryProvider | None = None,
) -> LLMRecoveryResult:
    metrics = LLMRecoveryMetrics()
    manual_review_flags: list[str] = []
    trigger_reasons = llm_recovery_trigger_reasons(
        resume_text=resume_text,
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
    )
    metrics.trigger_reasons = trigger_reasons
    metrics.enabled = llm_recovery_enabled()

    if not metrics.enabled:
        metrics.skipped_reason = "llm_recovery_disabled"
        return _result(
            full_name=full_name,
            email=email,
            phone=phone,
            location=location,
            skills=skills,
            employment_history=employment_history,
            education=education,
            certifications=certifications,
            manual_review_flags=manual_review_flags,
            metrics=metrics,
        )

    if not trigger_reasons:
        metrics.available = provider is not None or langchain_openai_available()
        metrics.skipped_reason = "llm_recovery_not_needed"
        return _result(
            full_name=full_name,
            email=email,
            phone=phone,
            location=location,
            skills=skills,
            employment_history=employment_history,
            education=education,
            certifications=certifications,
            manual_review_flags=manual_review_flags,
            metrics=metrics,
        )

    if not resume_text.strip():
        metrics.skipped_reason = "resume_text_unusable"
        return _result(
            full_name=full_name,
            email=email,
            phone=phone,
            location=location,
            skills=skills,
            employment_history=employment_history,
            education=education,
            certifications=certifications,
            manual_review_flags=manual_review_flags,
            metrics=metrics,
        )

    active_provider = provider or default_llm_recovery_provider()
    metrics.available = active_provider is not None
    if active_provider is None:
        metrics.skipped_reason = "llm_provider_unavailable"
        return _result(
            full_name=full_name,
            email=email,
            phone=phone,
            location=location,
            skills=skills,
            employment_history=employment_history,
            education=education,
            certifications=certifications,
            manual_review_flags=manual_review_flags,
            metrics=metrics,
        )

    try:
        metrics.called = True
        recovery = active_provider.recover(
            resume_text=resume_text,
            trigger_reasons=trigger_reasons,
        )
        recovery = LLMExtractionRecovery.model_validate(recovery)
    except Exception as exc:
        metrics.validation_error_count += 1
        metrics.skipped_reason = "llm_recovery_failed"
        manual_review_flags.append(f"LLM extraction recovery failed validation: {exc}")
        return _result(
            full_name=full_name,
            email=email,
            phone=phone,
            location=location,
            skills=skills,
            employment_history=employment_history,
            education=education,
            certifications=certifications,
            manual_review_flags=manual_review_flags,
            metrics=metrics,
        )

    merge = _merge_recovery(
        recovery=recovery,
        resume_text=resume_text,
        source_path=source_path,
        full_name=full_name,
        email=email,
        phone=phone,
        location=location,
        skills=skills,
        employment_history=employment_history,
        education=education,
        certifications=certifications,
        metrics=metrics,
    )
    merge.metrics.final_extraction_mode = (
        "deterministic_plus_llm"
        if merge.metrics.accepted_field_count > 0
        else "deterministic"
    )
    return merge


def llm_recovery_enabled() -> bool:
    return os.getenv(LLM_EXTRACTION_ENABLED_ENV, "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def llm_recovery_max_tokens() -> int:
    raw_value = os.getenv(LLM_EXTRACTION_MAX_TOKENS_ENV, "").strip()
    if not raw_value:
        return DEFAULT_LLM_EXTRACTION_MAX_TOKENS

    try:
        parsed = int(raw_value)
    except ValueError:
        return DEFAULT_LLM_EXTRACTION_MAX_TOKENS

    if parsed < 1:
        return DEFAULT_LLM_EXTRACTION_MAX_TOKENS

    return parsed


def langchain_openai_available() -> bool:
    if not os.getenv(OPENAI_API_KEY_ENV):
        return False

    try:
        import langchain_openai  # noqa: F401
    except ImportError:
        return False

    return True


def default_llm_recovery_provider() -> LLMRecoveryProvider | None:
    if not os.getenv(OPENAI_API_KEY_ENV):
        return None

    if not langchain_openai_available():
        return None

    return LangChainOpenAIRecoveryProvider()


def llm_recovery_trigger_reasons(
    *,
    resume_text: str,
    full_name: ExtractedField,
    email: ExtractedField | None,
    phone: ExtractedField | None,
    location: ExtractedField | None,
    skills: list[SkillRecord],
    employment_history: list[EmploymentRecord],
    education: list[EducationRecord],
    certifications: list[CertificationRecord],
    extraction_confidence: float,
    section_confidence: dict[str, float],
) -> list[str]:
    reasons: list[str] = []

    if extraction_confidence < 0.60:
        reasons.append("low_extraction_confidence")

    if not full_name.value and resume_text.strip():
        reasons.append("missing_required_full_name")

    if email is None and phone is None:
        reasons.append("missing_contact_channels")

    empty_count = _empty_recovery_section_count(
        resume_text=resume_text,
        email=email,
        phone=phone,
        location=location,
        skills=skills,
        employment_history=employment_history,
        education=education,
        certifications=certifications,
    )
    if empty_count >= 3:
        reasons.append("many_empty_profile_sections")

    if (
        not employment_history
        and section_confidence.get("employment_history", 0.0) == 0.0
        and _has_section_like_text(resume_text, ("experience", "employment", "work history"))
    ):
        reasons.append("employment_section_missing")

    if (
        not education
        and section_confidence.get("education", 0.0) == 0.0
        and _has_section_like_text(resume_text, ("education", "academic", "university"))
    ):
        reasons.append("education_section_missing")

    return reasons


def _merge_recovery(
    *,
    recovery: LLMExtractionRecovery,
    resume_text: str,
    source_path: Path,
    full_name: ExtractedField,
    email: ExtractedField | None,
    phone: ExtractedField | None,
    location: ExtractedField | None,
    skills: list[SkillRecord],
    employment_history: list[EmploymentRecord],
    education: list[EducationRecord],
    certifications: list[CertificationRecord],
    metrics: LLMRecoveryMetrics,
) -> LLMRecoveryResult:
    manual_review_flags: list[str] = [
        f"LLM recovery rejected item: {item.reason}"
        for item in recovery.rejected_items
    ]
    metrics.rejected_field_count += len(recovery.rejected_items)

    full_name = _maybe_fill_field(
        current=full_name,
        candidate=recovery.full_name,
        resume_text=resume_text,
        source_path=source_path,
        section="contact",
        field_path="full_name",
        evidence_id="ev_llm_contact_full_name_001",
        metrics=metrics,
        manual_review_flags=manual_review_flags,
    )
    email = _maybe_fill_optional_field(
        current=email,
        candidate=recovery.email,
        resume_text=resume_text,
        source_path=source_path,
        section="contact",
        field_path="email",
        evidence_id="ev_llm_contact_email_001",
        metrics=metrics,
        manual_review_flags=manual_review_flags,
    )
    phone = _maybe_fill_optional_field(
        current=phone,
        candidate=recovery.phone,
        resume_text=resume_text,
        source_path=source_path,
        section="contact",
        field_path="phone",
        evidence_id="ev_llm_contact_phone_001",
        metrics=metrics,
        manual_review_flags=manual_review_flags,
    )
    location = _maybe_fill_optional_field(
        current=location,
        candidate=recovery.location,
        resume_text=resume_text,
        source_path=source_path,
        section="contact",
        field_path="location",
        evidence_id="ev_llm_contact_location_001",
        metrics=metrics,
        manual_review_flags=manual_review_flags,
    )

    skills = _merge_skills(
        current=skills,
        candidates=recovery.skills,
        resume_text=resume_text,
        source_path=source_path,
        metrics=metrics,
        manual_review_flags=manual_review_flags,
    )
    employment_history = _merge_employment_history(
        current=employment_history,
        candidates=recovery.employment_history,
        resume_text=resume_text,
        source_path=source_path,
        metrics=metrics,
        manual_review_flags=manual_review_flags,
    )
    education = _merge_education(
        current=education,
        candidates=recovery.education,
        resume_text=resume_text,
        source_path=source_path,
        metrics=metrics,
        manual_review_flags=manual_review_flags,
    )
    certifications = _merge_certifications(
        current=certifications,
        candidates=recovery.certifications,
        resume_text=resume_text,
        source_path=source_path,
        metrics=metrics,
        manual_review_flags=manual_review_flags,
    )

    return _result(
        full_name=full_name,
        email=email,
        phone=phone,
        location=location,
        skills=skills,
        employment_history=employment_history,
        education=education,
        certifications=certifications,
        manual_review_flags=manual_review_flags,
        metrics=metrics,
    )


def _maybe_fill_field(
    *,
    current: ExtractedField,
    candidate: LLMExtractedField | None,
    resume_text: str,
    source_path: Path,
    section: str,
    field_path: str,
    evidence_id: str,
    metrics: LLMRecoveryMetrics,
    manual_review_flags: list[str],
) -> ExtractedField:
    if current.value and current.evidence:
        return current

    accepted = _accepted_llm_field(
        candidate=candidate,
        resume_text=resume_text,
        source_path=source_path,
        section=section,
        field_path=field_path,
        evidence_id=evidence_id,
        metrics=metrics,
        manual_review_flags=manual_review_flags,
    )
    return accepted or current


def _maybe_fill_optional_field(
    *,
    current: ExtractedField | None,
    candidate: LLMExtractedField | None,
    resume_text: str,
    source_path: Path,
    section: str,
    field_path: str,
    evidence_id: str,
    metrics: LLMRecoveryMetrics,
    manual_review_flags: list[str],
) -> ExtractedField | None:
    if current and current.value and current.evidence:
        return current

    return _accepted_llm_field(
        candidate=candidate,
        resume_text=resume_text,
        source_path=source_path,
        section=section,
        field_path=field_path,
        evidence_id=evidence_id,
        metrics=metrics,
        manual_review_flags=manual_review_flags,
    ) or current


def _accepted_llm_field(
    *,
    candidate: LLMExtractedField | None,
    resume_text: str,
    source_path: Path,
    section: str,
    field_path: str,
    evidence_id: str,
    metrics: LLMRecoveryMetrics,
    manual_review_flags: list[str],
) -> ExtractedField | None:
    if candidate is None or not candidate.value:
        return None

    evidence = _accepted_evidence(
        value=candidate.value,
        snippet=candidate.source_snippet,
        resume_text=resume_text,
        source_path=source_path,
        section=section,
        field_path=field_path,
        evidence_id=evidence_id,
        confidence=candidate.confidence,
        metrics=metrics,
        manual_review_flags=manual_review_flags,
    )
    if evidence is None:
        return None

    metrics.accepted_field_count += 1
    return ExtractedField(
        value=candidate.value,
        confidence=candidate.confidence,
        evidence=[evidence],
    )


def _merge_skills(
    *,
    current: list[SkillRecord],
    candidates: list[LLMSkill],
    resume_text: str,
    source_path: Path,
    metrics: LLMRecoveryMetrics,
    manual_review_flags: list[str],
) -> list[SkillRecord]:
    merged = list(current)
    existing = {skill.normalized_name for skill in merged}

    for candidate in candidates:
        normalized = candidate.normalized_name or slugify(candidate.name)
        if normalized in existing:
            continue

        evidence = _accepted_evidence(
            value=candidate.name,
            snippet=candidate.source_snippet,
            resume_text=resume_text,
            source_path=source_path,
            section="skills",
            field_path=f"skills[{len(merged)}]",
            evidence_id=f"ev_llm_skill_{slugify(candidate.name)}_001",
            confidence=candidate.confidence,
            metrics=metrics,
            manual_review_flags=manual_review_flags,
        )
        if evidence is None:
            continue

        merged.append(
            SkillRecord(
                name=candidate.name,
                normalized_name=normalized,
                category=candidate.category,
                confidence=candidate.confidence,
                evidence=[evidence],
            )
        )
        existing.add(normalized)
        metrics.accepted_field_count += 1

    return merged


def _merge_employment_history(
    *,
    current: list[EmploymentRecord],
    candidates: list[LLMEmployment],
    resume_text: str,
    source_path: Path,
    metrics: LLMRecoveryMetrics,
    manual_review_flags: list[str],
) -> list[EmploymentRecord]:
    if current and all(record.company and record.title for record in current):
        return current

    merged = list(current)
    existing = {normalize_whitespace(record.company).lower() for record in merged}

    for candidate in candidates:
        company_key = normalize_whitespace(candidate.company).lower()
        if company_key in existing:
            continue

        evidence = _accepted_evidence(
            value=candidate.company,
            snippet=candidate.source_snippet,
            resume_text=resume_text,
            source_path=source_path,
            section="employment_history",
            field_path=f"employment_history[{len(merged)}]",
            evidence_id=f"ev_llm_employment_{len(merged)}_001",
            confidence=candidate.confidence,
            metrics=metrics,
            manual_review_flags=manual_review_flags,
        )
        if evidence is None:
            continue

        merged.append(
            EmploymentRecord(
                company=candidate.company,
                title=candidate.title,
                start_date=candidate.start_date,
                end_date=candidate.end_date,
                is_current=candidate.is_current,
                responsibilities=candidate.responsibilities,
                confidence=candidate.confidence,
                evidence=[evidence],
            )
        )
        existing.add(company_key)
        metrics.accepted_field_count += 1

    return merged


def _merge_education(
    *,
    current: list[EducationRecord],
    candidates: list[LLMEducation],
    resume_text: str,
    source_path: Path,
    metrics: LLMRecoveryMetrics,
    manual_review_flags: list[str],
) -> list[EducationRecord]:
    if current and all(record.institution for record in current):
        return current

    merged = list(current)
    existing = {normalize_whitespace(record.institution).lower() for record in merged}

    for candidate in candidates:
        institution_key = normalize_whitespace(candidate.institution).lower()
        if institution_key in existing:
            continue

        evidence = _accepted_evidence(
            value=candidate.institution,
            snippet=candidate.source_snippet,
            resume_text=resume_text,
            source_path=source_path,
            section="education",
            field_path=f"education[{len(merged)}]",
            evidence_id=f"ev_llm_education_{len(merged)}_001",
            confidence=candidate.confidence,
            metrics=metrics,
            manual_review_flags=manual_review_flags,
        )
        if evidence is None:
            continue

        merged.append(
            EducationRecord(
                institution=candidate.institution,
                degree=candidate.degree,
                field_of_study=candidate.field_of_study,
                country=candidate.country,
                start_year=candidate.start_year,
                end_year=candidate.end_year,
                is_international=candidate.is_international,
                verification_status=candidate.verification_status,
                confidence=candidate.confidence,
                evidence=[evidence],
            )
        )
        existing.add(institution_key)
        metrics.accepted_field_count += 1

    return merged


def _merge_certifications(
    *,
    current: list[CertificationRecord],
    candidates: list[LLMCertification],
    resume_text: str,
    source_path: Path,
    metrics: LLMRecoveryMetrics,
    manual_review_flags: list[str],
) -> list[CertificationRecord]:
    merged = list(current)
    existing = {normalize_whitespace(record.name).lower() for record in merged}

    for candidate in candidates:
        name_key = normalize_whitespace(candidate.name).lower()
        if name_key in existing:
            continue

        evidence = _accepted_evidence(
            value=candidate.name,
            snippet=candidate.source_snippet,
            resume_text=resume_text,
            source_path=source_path,
            section="certification",
            field_path=f"certifications[{len(merged)}].name",
            evidence_id=f"ev_llm_certification_{len(merged)}_001",
            confidence=candidate.confidence,
            metrics=metrics,
            manual_review_flags=manual_review_flags,
        )
        if evidence is None:
            continue

        merged.append(
            CertificationRecord(
                name=candidate.name,
                issuer=candidate.issuer,
                issued_date=candidate.issued_date,
                expiration_date=candidate.expiration_date,
                credential_id=candidate.credential_id,
                verification_status=candidate.verification_status,
                confidence=candidate.confidence,
                evidence=[evidence],
            )
        )
        existing.add(name_key)
        metrics.accepted_field_count += 1

    return merged


def _accepted_evidence(
    *,
    value: str,
    snippet: str,
    resume_text: str,
    source_path: Path,
    section: str,
    field_path: str,
    evidence_id: str,
    confidence: float,
    metrics: LLMRecoveryMetrics,
    manual_review_flags: list[str],
) -> EvidenceRef | None:
    if _contains_recommendation_language(value) or _contains_recommendation_language(snippet):
        metrics.recommendation_violation_count += 1
        metrics.rejected_field_count += 1
        manual_review_flags.append(
            f"LLM recovery rejected `{field_path}` because it contained recommendation language."
        )
        return None

    if not _snippet_in_resume(snippet, resume_text):
        metrics.rejected_field_count += 1
        manual_review_flags.append(
            f"LLM recovery rejected `{field_path}` because source evidence was not found in the resume text."
        )
        return None

    normalized_snippet = normalize_whitespace(snippet)[:240]
    return EvidenceRef(
        evidence_id=evidence_id,
        field_path=field_path,
        source_path=source_path,
        source_type="resume_pdf" if source_path.suffix.lower() == ".pdf" else "resume_text",
        page_number=None,
        section=section,
        text_snippet=normalized_snippet,
        confidence=confidence,
        extraction_method="llm_recovery",
    )


def _contains_recommendation_language(value: str | None) -> bool:
    if not value:
        return False

    normalized = normalize_whitespace(value).lower()
    return any(
        re.search(rf"\b{re.escape(term)}(?:ed|ing|s|ation)?\b", normalized)
        for term in RECOMMENDATION_TERMS
    )


def _snippet_in_resume(snippet: str, resume_text: str) -> bool:
    return normalize_whitespace(snippet).lower() in normalize_whitespace(resume_text).lower()


def _empty_recovery_section_count(
    *,
    resume_text: str,
    email: ExtractedField | None,
    phone: ExtractedField | None,
    location: ExtractedField | None,
    skills: list[SkillRecord],
    employment_history: list[EmploymentRecord],
    education: list[EducationRecord],
    certifications: list[CertificationRecord],
) -> int:
    empty_count = 0

    if email is None or not email.value:
        empty_count += 1
    if phone is None or not phone.value:
        empty_count += 1
    if location is None or not location.value:
        empty_count += 1
    if not skills:
        empty_count += 1
    if not employment_history and _has_section_like_text(
        resume_text,
        ("experience", "employment", "work history"),
    ):
        empty_count += 1
    if not education and _has_section_like_text(
        resume_text,
        ("education", "academic", "university"),
    ):
        empty_count += 1
    if not certifications and _has_section_like_text(
        resume_text,
        ("certification", "certifications", "certificate", "certified"),
    ):
        empty_count += 1

    return empty_count


def _has_section_like_text(resume_text: str, labels: tuple[str, ...]) -> bool:
    normalized = normalize_whitespace(resume_text).lower()
    return any(label in normalized for label in labels)


def _result(
    *,
    full_name: ExtractedField,
    email: ExtractedField | None,
    phone: ExtractedField | None,
    location: ExtractedField | None,
    skills: list[SkillRecord],
    employment_history: list[EmploymentRecord],
    education: list[EducationRecord],
    certifications: list[CertificationRecord],
    manual_review_flags: list[str],
    metrics: LLMRecoveryMetrics,
) -> LLMRecoveryResult:
    metrics.manual_review_flag_count = len(manual_review_flags)
    return LLMRecoveryResult(
        full_name=full_name,
        email=email,
        phone=phone,
        location=location,
        skills=skills,
        employment_history=employment_history,
        education=education,
        certifications=certifications,
        manual_review_flags=manual_review_flags,
        metrics=metrics,
    )


def _system_prompt() -> str:
    return (
        "You are an assistive resume parsing helper. Extract only factual resume "
        "fields that are directly supported by source snippets from the resume. "
        "Do not make hiring, rejection, compliance, routing, ranking, or final "
        "decision recommendations. Do not use words such as hire, reject, "
        "qualified, unqualified, good, bad, advance, shortlist, or recommend."
    )


def _human_prompt(*, resume_text: str, trigger_reasons: list[str]) -> str:
    return (
        "Recovery triggers: "
        f"{', '.join(trigger_reasons) or 'none'}\n\n"
        "Return only schema-valid factual fields. Every field must include an "
        "exact source_snippet copied from the resume text.\n\n"
        f"Resume text:\n{resume_text}"
    )
