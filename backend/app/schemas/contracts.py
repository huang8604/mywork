from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


ReviewStatus = Literal["known", "unknown", "skipped"]
ReviewSource = Literal["quick_review", "online_practice", "print_manual"]
RoundMode = Literal["offline", "online"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


_ENGLISH_WORD = re.compile(r"^[A-Za-z][A-Za-z '\-]*$")
NonEmpty200 = Annotated[
    str,
    Field(min_length=1, max_length=200, pattern=r"^\s*[A-Za-z][A-Za-z '\-]*\s*$"),
]


def _validate_english_word(value: str) -> str:
    if not _ENGLISH_WORD.fullmatch(value.strip()):
        raise ValueError("must use English letters, spaces, apostrophes or hyphens")
    return value


class WordCreate(StrictModel):
    en_word: NonEmpty200
    phonetic: str | None = Field(default=None, max_length=200)
    cn_meaning: str | None = Field(default=None, max_length=2000)
    example_sentence: str | None = Field(default=None, max_length=5000)
    is_custom: bool = False
    tags: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("en_word")
    @classmethod
    def english_word_only(cls, value: str) -> str:
        return _validate_english_word(value)

    @field_validator("phonetic", "cn_meaning", "example_sentence")
    @classmethod
    def empty_to_none(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @field_validator("tags")
    @classmethod
    def unique_tags(cls, values: list[str]) -> list[str]:
        if len({value.casefold().strip() for value in values}) != len(values):
            raise ValueError("tags must be unique after normalization")
        return values


class WordUpdate(StrictModel):
    en_word: NonEmpty200
    phonetic: str | None = Field(default=None, max_length=200)
    cn_meaning: str = Field(min_length=1, max_length=2000)
    example_sentence: str | None = Field(default=None, max_length=5000)
    is_custom: bool
    tags: list[str] = Field(max_length=20)
    expected_version: int = Field(gt=0)

    @field_validator("en_word")
    @classmethod
    def english_word_only(cls, value: str) -> str:
        return _validate_english_word(value)

    @field_validator("phonetic", "example_sentence")
    @classmethod
    def empty_to_none(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @field_validator("tags")
    @classmethod
    def unique_tags(cls, values: list[str]) -> list[str]:
        if len({value.casefold().strip() for value in values}) != len(values):
            raise ValueError("tags must be unique after normalization")
        return values


class WordEnrichRequest(StrictModel):
    words: list[NonEmpty200] = Field(min_length=1, max_length=200)
    allow_ai: bool = False

    @field_validator("words")
    @classmethod
    def unique_words(cls, values: list[str]) -> list[str]:
        for value in values:
            _validate_english_word(value)
        normalized = [value.casefold().strip() for value in values]
        if len(normalized) != len(set(normalized)):
            raise ValueError("words must be unique after normalization")
        return values


class ReviewCreate(StrictModel):
    word_id: int = Field(gt=0)
    status: ReviewStatus
    source: Literal["quick_review"] = "quick_review"
    client_event_id: str = Field(min_length=1, max_length=128)
    duration_ms: int | None = Field(default=None, ge=0, le=86_400_000)
    reviewed_at: datetime | None = None


class ReviewCorrection(StrictModel):
    status: ReviewStatus
    reviewed_at: datetime | None = None
    duration_ms: int | None = Field(default=None, ge=0, le=86_400_000)
    client_event_id: str = Field(min_length=1, max_length=128)
    expected_version: int = Field(gt=0)


class StrategyRequest(StrictModel):
    new_words_limit: int = Field(default=10, ge=0, le=100)
    error_words_limit: int = Field(default=15, ge=0, le=100)
    due_words_limit: int = Field(default=20, ge=0, le=100)
    custom_words_limit: int = Field(default=5, ge=0, le=100)
    fallback_unreviewed_days: int = Field(default=3, ge=1, le=365)
    seed: int | None = Field(default=None, ge=0, le=2_147_483_647)
    word_ids: list[int] = Field(default_factory=list, max_length=200)

    @field_validator("word_ids")
    @classmethod
    def unique_word_ids(cls, values: list[int]) -> list[int]:
        if any(value <= 0 for value in values):
            raise ValueError("word_ids must contain positive integers")
        if len(values) != len(set(values)):
            raise ValueError("word_ids must be unique")
        return values


class RoundCreate(StrictModel):
    mode: RoundMode
    started_at: datetime | None = None


class RoundResult(StrictModel):
    status: ReviewStatus
    client_event_id: str = Field(min_length=1, max_length=128)
    duration_ms: int | None = Field(default=None, ge=0, le=86_400_000)
    reviewed_at: datetime | None = None
    expected_version: int | None = Field(default=None, gt=0)


class BatchRoundResult(RoundResult):
    item_id: int = Field(gt=0)


class BatchResults(StrictModel):
    items: list[BatchRoundResult] = Field(min_length=1)

    @model_validator(mode="after")
    def no_duplicates(self) -> "BatchResults":
        item_ids = [item.item_id for item in self.items]
        event_ids = [item.client_event_id for item in self.items]
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("duplicate item_id")
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("duplicate client_event_id")
        return self


class ImportOptions(StrictModel):
    conflict_policy: Literal["skip", "update", "reject"] = "reject"
    unresolved_policy: Literal["skip", "reject", "ai"] = "reject"
    dry_run: bool = False


class VersionRequest(StrictModel):
    expected_version: int = Field(gt=0)


class SessionUpdate(StrictModel):
    title: str | None = Field(default=None, max_length=200)
    note: str | None = Field(default=None, max_length=5000)
    expected_version: int = Field(gt=0)
