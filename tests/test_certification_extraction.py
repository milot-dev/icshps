from icshps.agents.extraction import (
    extract_candidate_profile,
)
from icshps.schemas.profile import CertificationRecord


def make_profile_from_text(text: str):
    return extract_candidate_profile(
        text,
        candidate_id="cid",
        application_id="aid",
        role_id="rid",
        source_file="resume.txt",
    )


def test_single_certification_parsed():
    text = "John Doe\nProfessional Data Scientist - DataCert 2021"
    profile = make_profile_from_text(text)
    assert len(profile.certifications) == 1
    cert = profile.certifications[0]
    assert isinstance(cert, CertificationRecord)
    assert "Professional Data Scientist" in cert.name
    assert cert.issuer is not None
    assert cert.issued_date == "2021"


def test_multiple_certifications_parsed():
    text = (
        "Jane Smith\n"
        "Certified Cloud Practitioner, CloudOrg, 2019\n"
        "Certified Scrum Master - ScrumOrg 2020\n"
    )
    profile = make_profile_from_text(text)
    assert len(profile.certifications) >= 2


def test_certification_with_by_issuer():
    text = "Alex Johnson\nAWS Certified Solutions Architect by Amazon 2018"
    profile = make_profile_from_text(text)
    assert len(profile.certifications) == 1
    cert = profile.certifications[0]
    assert "AWS Certified Solutions Architect" in cert.name
    assert "Amazon" in (cert.issuer or "")
    assert cert.issued_date == "2018"


def test_no_certifications_returns_empty_list():
    text = "Experienced software engineer with 5 years experience."
    profile = make_profile_from_text(text)
    assert isinstance(profile.certifications, list)
    assert len(profile.certifications) == 0
