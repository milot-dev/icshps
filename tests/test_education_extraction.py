from __future__ import annotations

from pathlib import Path
from icshps.agents.extraction.education_extractor import (
    extract_education_records,
    clean_education_line,
    group_lines_into_education_blocks,
    contains_institution,
    contains_degree,
)
from icshps.schemas.profile import EducationRecord


def dummy_make_evidence(
    source_path: Path,
    education_index: int,
    snippet: str,
    confidence: float,
):
    from icshps.schemas.common import EvidenceRef
    return EvidenceRef(
        evidence_id=f"ev_education_{education_index}_record_001",
        field_path=f"education[{education_index}]",
        source_path=source_path,
        source_type="resume_text",
        section="education",
        text_snippet=snippet,
        confidence=confidence,
        extraction_method="regex_resume_text",
    )


def test_clean_education_line():
    assert clean_education_line("Education: MSc Computer Science") == "MSc Computer Science"
    assert clean_education_line("Academic Qualifications: PhD Physics") == "PhD Physics"
    assert clean_education_line("Normal Line") == "Normal Line"


def test_contains_institution_and_degree():
    assert contains_institution("University of Pristina") is True
    assert contains_institution("Pristina High School") is True
    assert contains_institution("Just some company") is False

    assert contains_degree("Bachelor of Science") is True
    assert contains_degree("B.Sc. in Physics") is True
    assert contains_degree("Master of Science") is True
    assert contains_degree("MSc") is True
    assert contains_degree("PhD Computer Science") is True
    assert contains_degree("Just some text") is False


def test_group_lines_into_blocks():
    lines = [
        "University of Pristina",
        "Bachelor of Science",
        "2018 - 2022",
        "International Technical University",
        "MSc Computer Science, 2024",
    ]
    blocks = group_lines_into_education_blocks(lines)
    assert len(blocks) == 2
    assert blocks[0] == ["University of Pristina", "Bachelor of Science", "2018 - 2022"]
    assert blocks[1] == ["International Technical University", "MSc Computer Science, 2024"]


def test_extract_education_records_single_line():
    lines = [
        "Education: MSc Computer Science, International Technical University, 2022"
    ]
    records = extract_education_records(lines, Path("resume.txt"), dummy_make_evidence)
    assert len(records) == 1
    rec = records[0]
    assert isinstance(rec, EducationRecord)
    assert rec.institution == "International Technical University"
    assert rec.degree == "MSc Computer Science"
    assert rec.field_of_study == "Computer Science"
    assert rec.country == "Non-local jurisdiction"
    assert rec.end_year == 2022
    assert rec.is_international is True


def test_extract_education_records_multi_line():
    lines = [
        "Education:",
        "University of Pristina",
        "Bachelor of Science in Computer Engineering",
        "Graduation Year: 2020",
    ]
    records = extract_education_records(lines, Path("resume.txt"), dummy_make_evidence)
    assert len(records) == 1
    rec = records[0]
    assert rec.institution == "University of Pristina"
    assert rec.degree == "Bachelor of Science in Computer Engineering"
    assert rec.field_of_study == "Computer Engineering"
    assert rec.end_year == 2020
    # Pristina is local to Kosovo
    assert rec.is_international is False


def test_extract_education_records_multiple():
    lines = [
        "Education",
        "University of Pristina",
        "BSc Computer Science, 2018 - 2021",
        "International Technical University",
        "MSc in AI, 2021-2023",
    ]
    records = extract_education_records(lines, Path("resume.txt"), dummy_make_evidence)
    assert len(records) == 2
    
    rec1 = records[0]
    assert rec1.institution == "University of Pristina"
    assert rec1.degree == "BSc Computer Science"
    assert rec1.field_of_study == "Computer Science"
    assert rec1.start_year == 2018
    assert rec1.end_year == 2021
    assert rec1.is_international is False

    rec2 = records[1]
    assert rec2.institution == "International Technical University"
    assert rec2.degree == "MSc in AI"
    assert rec2.field_of_study == "AI"
    assert rec2.start_year == 2021
    assert rec2.end_year == 2023
    assert rec2.is_international is True
