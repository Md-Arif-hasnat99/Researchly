from datetime import datetime, timezone

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Health check response schema."""

    status: str = Field(default="ok", examples=["ok"])
    version: str = Field(default="0.1.0", examples=["0.1.0"])
    service: str = Field(default="researchly-api", examples=["researchly-api"])
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        examples=["2026-09-23T17:45:00Z"],
    )
    dependencies: dict[str, str] = Field(default_factory=dict)
