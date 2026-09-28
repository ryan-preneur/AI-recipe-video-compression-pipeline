from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field, model_validator, field_validator

LANGUAGES = {"en": ("English", "en-US"), "hi": ("Hindi", "hi-IN"), "ta": ("Tamil", "ta-IN"), "bn": ("Bengali", "bn-IN"), "kn": ("Kannada", "kn-IN")}

class CreateJob(BaseModel):
    url: str
    duration: Literal[30, 60, 90, 120]
    output_language: Literal["en", "hi", "ta", "bn", "kn"]
    source_language: Literal["auto", "en", "hi", "ta", "bn", "kn"] = "auto"

class Segment(BaseModel):
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    text: str
    uncertain: bool = False
    @model_validator(mode="after")
    def valid_time(self):
        if self.end <= self.start: raise ValueError("End must follow start")
        return self

class Cut(BaseModel):
    id: str
    source_start: float = Field(ge=0)
    source_end: float = Field(gt=0)
    purpose: str = Field(min_length=1, max_length=160)
    source_evidence: str = Field(min_length=1, max_length=800)
    narration_text: str = Field(min_length=1, max_length=900)
    uncertain: bool = False
    @model_validator(mode="after")
    def valid_time(self):
        if self.source_end <= self.source_start: raise ValueError("Cut end must follow start")
        return self

class Draft(BaseModel):
    dish: str
    source_language: str
    output_language: str
    transcript: list[Segment]
    cuts: list[Cut]
    warnings: list[str] = []

class DraftUpdate(BaseModel):
    source_language: str
    transcript: list[Segment]
    cuts: list[Cut]

class RenderRequest(BaseModel):
    speed: float = 1.0

    @field_validator('speed')
    @classmethod
    def validate_speed(cls, value):
        if value not in {1.0,1.25,1.5,1.75,2.0,2.5,3.0,4.0}:
            raise ValueError('Choose a supported reel speed')
        return value
