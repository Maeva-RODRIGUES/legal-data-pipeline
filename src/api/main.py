from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import date
from typing import Annotated, Any

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .backends import (
    Database,
    ElasticsearchBackend,
    PostgresDatabase,
    SearchBackend,
    ServiceUnavailable,
    load_settings,
)
from .display import display_title
from .models import (
    CheckStatus,
    Decision,
    DecisionType,
    ErrorResponse,
    HealthResponse,
    QualityResponse,
    RunsResponse,
    RunStatus,
    SearchResponse,
    Source,
)
from .search import MAX_RESULT_WINDOW, Filters, build_body, format_hits, total_hits

logger = logging.getLogger(__name__)

MAX_QUERY_LENGTH = 500
MAX_NUMBER_LENGTH = 100
HTTP_CODES = {404: "not_found", 405: "method_not_allowed"}


class ApiError(Exception):
    """Erreur prévue par le contrat, rendue dans l'enveloppe {"error": ...}."""

    def __init__(self, status: int, code: str, message: str, field: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.field = field


def invalid(message: str, field: str | None = None) -> ApiError:
    return ApiError(422, "invalid_parameter", message, field)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    load_dotenv()
    settings = load_settings(os.environ)  # variable manquante : l'application ne démarre pas
    app.state.search = ElasticsearchBackend.from_url(settings.elasticsearch_url)
    app.state.database = PostgresDatabase(settings.database_url)
    try:
        yield
    finally:
        app.state.search.close()


app = FastAPI(
    title="legal-data-pipeline",
    version="0.4.0",
    description="Recherche dans les décisions de justice et d'autorités (lecture seule) : "
    "index Elasticsearch `decisions`, couche Silver, runs du pipeline et contrôles qualité.",
    lifespan=lifespan,
)


def get_search(request: Request) -> SearchBackend:
    return request.app.state.search


def get_database(request: Request) -> Database:
    return request.app.state.database


SearchDep = Annotated[SearchBackend, Depends(get_search)]
DatabaseDep = Annotated[Database, Depends(get_database)]


# Erreurs ------------------------------------------------------------------------


def error_response(
    status: int, code: str, message: str, details: list[dict[str, Any]] | None = None
) -> JSONResponse:
    body = {"error": {"code": code, "message": message, "details": details or []}}
    return JSONResponse(status_code=status, content=body)


@app.exception_handler(ApiError)
async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    details = [{"field": exc.field, "message": exc.message}] if exc.status == 422 else []
    return error_response(exc.status, exc.code, exc.message, details)


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    details = [
        {"field": ".".join(str(part) for part in error["loc"][1:]) or None, "message": error["msg"]}
        for error in exc.errors()
    ]
    fields = ", ".join(sorted({d["field"] for d in details if d["field"]}))
    return error_response(422, "invalid_parameter", f"invalid parameter(s): {fields}", details)


@app.exception_handler(ServiceUnavailable)
async def unavailable_handler(request: Request, exc: ServiceUnavailable) -> JSONResponse:
    logger.warning("%s: %r", exc.code, exc.__cause__ or exc)
    return error_response(503, exc.code, exc.message)


@app.exception_handler(StarletteHTTPException)
async def http_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    return error_response(
        exc.status_code, HTTP_CODES.get(exc.status_code, "http_error"), exc.detail
    )


@app.exception_handler(Exception)
async def internal_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled error on %s", request.url.path)  # détail dans les logs seulement
    return error_response(500, "internal_error", "internal server error")


ERRORS: dict[int | str, dict[str, Any]] = {
    status: {"model": ErrorResponse} for status in (404, 422, 503)
}


# Routes -------------------------------------------------------------------------


def clean(value: str | None, name: str, max_length: int) -> str | None:
    """Espaces autour retirés ; vide ou trop long : paramètre invalide."""
    if value is None:
        return None
    value = value.strip()
    if not value:
        raise invalid(f"{name} must not be empty", name)
    if len(value) > max_length:
        raise invalid(f"{name} must be at most {max_length} characters", name)
    return value


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse("/docs")


@app.get(
    "/search",
    response_model=SearchResponse,
    responses={k: ERRORS[k] for k in (422, 503)},
    summary="Recherche plein texte ou par numéro",
)
def search(
    backend: SearchDep,
    q: Annotated[
        str | None, Query(description="Texte cherché dans le titre (pondéré) et le texte intégral")
    ] = None,
    number: Annotated[
        str | None, Query(description="Numéro exact de la décision, exclusif de q")
    ] = None,
    source: Annotated[list[Source] | None, Query()] = None,
    decision_type: Annotated[list[DecisionType] | None, Query()] = None,
    date_from: Annotated[date | None, Query(description="Incluse")] = None,
    date_to: Annotated[date | None, Query(description="Incluse")] = None,
    sector: Annotated[list[str] | None, Query(description="Valeur exacte")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=50)] = 10,
) -> dict[str, Any]:
    q = clean(q, "q", MAX_QUERY_LENGTH)
    number = clean(number, "number", MAX_NUMBER_LENGTH)
    if (q is None) == (number is None):
        raise invalid("exactly one of q and number is required")
    if date_from and date_to and date_from > date_to:
        raise invalid("date_from must be on or before date_to", "date_from")
    if page * page_size > MAX_RESULT_WINDOW:
        raise invalid(f"page × page_size must be at most {MAX_RESULT_WINDOW}", "page")

    filters = Filters(source or [], decision_type or [], date_from, date_to, sector or [])
    response = backend.search(build_body(q, number, filters, page, page_size))
    return {
        "query": q,
        "number": number,
        "filters": asdict(filters),
        "page": page,
        "page_size": page_size,
        "total": total_hits(response),
        "results": format_hits(response),
    }


@app.get(
    "/decisions/{source}",
    response_model=Decision,
    responses=ERRORS,
    summary="Détail d'une décision (couche Silver)",
)
def decision(
    database: DatabaseDep,
    source: Source,
    external_id: Annotated[
        str, Query(alias="id", min_length=1, description="external_id, encodé dans l'URL")
    ],
) -> dict[str, Any]:
    row = database.decision(source, external_id)
    if row is None:
        raise ApiError(404, "decision_not_found", f"no decision {external_id!r} in {source}")
    title = display_title(
        row["title"], row["issuer"], row["decision_date"], row["decision_number"], external_id
    )
    return {**row, "display_title": title}


@app.get(
    "/runs",
    response_model=RunsResponse,
    responses={k: ERRORS[k] for k in (422, 503)},
    summary="Derniers runs du pipeline",
)
def runs(
    database: DatabaseDep,
    source: Annotated[list[str] | None, Query(description="Valeur exacte")] = None,
    status: RunStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict[str, Any]:
    return {"runs": database.runs(source or [], status, limit)}


@app.get(
    "/quality/latest",
    response_model=QualityResponse,
    responses=ERRORS,
    summary="Résultats du dernier run des contrôles qualité",
)
def quality_latest(
    database: DatabaseDep,
    status: Annotated[
        list[CheckStatus] | None, Query(description="Filtre les résultats, pas le verdict")
    ] = None,
) -> dict[str, Any]:
    report = database.latest_quality()
    if report is None:
        raise ApiError(404, "quality_results_not_found", "no quality results")
    if status:
        report["results"] = [r for r in report["results"] if r["status"] in status]
    return report


@app.get(
    "/health",
    response_model=HealthResponse,
    responses={503: {"model": HealthResponse}},
    summary="État de PostgreSQL et d'Elasticsearch",
)
def health(backend: SearchDep, database: DatabaseDep) -> JSONResponse:
    services = {"postgres": database.health(), "elasticsearch": backend.health()}
    ok = all(service["status"] == "ok" for service in services.values())
    body = HealthResponse(status="ok" if ok else "degraded", services=services)
    return JSONResponse(status_code=200 if ok else 503, content=jsonable_encoder(body))
