from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field


class TaskRequest(BaseModel):
    device_id: str
    action: str
    payload: dict = Field(default_factory=dict)
    humanize: bool = True
    media_type: Literal["audio", "video"] = "video"


class BatchStartRequest(BaseModel):
    clone_ids: list[str]
    humanize: bool = True
    media_type: Literal["audio", "video"] = "video"
    action: str = "sleep"
    payload: dict = Field(default_factory=dict)


class EmergencyStopRequest(BaseModel):
    reason: str = "manual_emergency"
    clone_ids: list[str] | None = None  # None = todos


class TargetCreate(BaseModel):
    url: str
    category: Literal["VIDEO", "AUDIO_STREAM", "SOCIAL_PROFILE", "PLAYLIST"]
    label: str | None = None
