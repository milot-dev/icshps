from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _deterministic_test_environment(
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> None:
    """Keep tests hermetic when a local .env enables live LLM extraction."""
    monkeypatch.delenv("ICSHPS_LLM_EXTRACTION_ENABLED", raising=False)
    monkeypatch.delenv("ICSHPS_VISION_OCR_ENABLED", raising=False)
    if request.node.get_closest_marker("live_api") is None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
