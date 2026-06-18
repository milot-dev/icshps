from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class AgentStageResult:
    """Controlled result returned by one orchestration-facing agent stage."""

    path: Path | None
    created_artifacts: tuple[str, ...]
    skipped_stages: tuple[str, ...]
    warnings: tuple[str, ...]
    payload: Any | None = None

    @property
    def created(self) -> bool:
        """Return True when the stage created its primary artifact."""

        return self.path is not None and not self.skipped_stages
