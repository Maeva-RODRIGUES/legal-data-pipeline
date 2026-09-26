from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel

# Vocabulaires de Silver et de src.quality ; leur concordance est vérifiée par les tests.
Source = Literal["judilibre", "adlc-opendata"]
DecisionType = Literal["concentration", "decision", "avis", "lettre_ministre"]
RunStatus = Literal["running", "success", "failed"]
CheckStatus = Literal["pass", "fail", "no_data", "unchecked", "query_error"]


class ErrorDetail(BaseModel):
    field: str | None
    message: str


class ErrorBody(BaseModel):
    code: str
    message: str
    details: list[ErrorDetail] = []


class ErrorResponse(BaseModel):
    error: ErrorBody


class SearchFilters(BaseModel):
    source: list[Source]
    decision_type: list[DecisionType]
    date_from: date | None
    date_to: date | None
    sector: list[str]


class Highlights(BaseModel):
    title: list[str]
    text: list[str]


class SearchHit(BaseModel):
    source: str
    external_id: str
    decision_number: str | None
    issuer: str | None
    decision_type: str | None
    decision_date: date | None
    title: str | None
    display_title: str
    sectors: list[str]
    url: str | None
    has_text: bool
    score: float | None
    highlights: Highlights
    detail_path: str


class SearchResponse(BaseModel):
    query: str | None
    number: str | None
    filters: SearchFilters
    page: int
    page_size: int
    total: int
    results: list[SearchHit]


class Decision(BaseModel):
    source: str
    external_id: str
    decision_number: str | None
    issuer: str | None
    decision_type: str | None
    decision_date: date | None
    title: str | None
    display_title: str
    text: str | None
    has_text: bool
    sectors: list[str]
    url: str | None
    attributes: dict[str, Any]
    built_at: datetime


class Run(BaseModel):
    run_id: int
    source: str
    date_type: str | None
    date_start: date
    date_end: date
    started_at: datetime
    finished_at: datetime | None
    status: str
    nb_fetched: int
    nb_new: int
    nb_changed: int
    error: str | None


class RunsResponse(BaseModel):
    runs: list[Run]


class QualityRun(BaseModel):
    run_id: int
    started_at: datetime
    finished_at: datetime | None
    status: str


class CheckResult(BaseModel):
    check_name: str
    dimension: str
    severity: str
    source: str | None
    value: int | float | None
    expected: str | None
    status: str
    error: str | None
    checked_at: datetime


class QualityResponse(BaseModel):
    run: QualityRun
    verdict: Literal["success", "failure"]
    counts: dict[str, int]
    results: list[CheckResult]


class PostgresHealth(BaseModel):
    status: Literal["ok", "error"]
    latency_ms: int
    error: str | None


class ElasticsearchHealth(PostgresHealth):
    index: str | None


class Services(BaseModel):
    postgres: PostgresHealth
    elasticsearch: ElasticsearchHealth


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    services: Services
