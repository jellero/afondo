"""Validated input models for untrusted API callers."""

from typing import Literal
from pydantic import BaseModel, Field, HttpUrl


class ArticleCreate(BaseModel):
    title: str = Field(min_length=5, max_length=300)
    text: str = Field(min_length=60, max_length=30_000)
    source_url: HttpUrl | None = None
    language: Literal["it", "en"] = "it"
    author: str | None = Field(default=None, max_length=200)
    outlet: str | None = Field(default=None, max_length=200)


class EvidenceCreate(BaseModel):
    url: HttpUrl
    stance: Literal["supports", "refutes", "unclear"]
    source_kind: Literal["primary", "secondary"]
    source_group: str = Field(min_length=2, max_length=180)
    note: str = Field(min_length=10, max_length=3000)


class EvidenceReview(BaseModel):
    decision: Literal["accepted", "rejected"]
