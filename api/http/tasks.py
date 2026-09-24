"""`POST /v1/tasks/ingest` -- external task ingress (SPEC 6.1a).

Source-authenticated (NFR-14): the bearer token identifies a connector, not a
participant, and a participant token is never accepted here. Responses:
201 new (source, external_id), 200 already seen (no duplicate row),
400 unknown field or non-JSON body, 401 missing/invalid source token,
422 missing or malformed required field.
"""

from __future__ import annotations

import hmac
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Mapping

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from config import endpoints

logger = logging.getLogger(__name__)
router = APIRouter()

MIN_TOKEN_LENGTH = 16


@dataclass(frozen=True)
class IngestDeps:
    """What the route needs: a store and the source -> token map."""

    store: Any
    source_tokens: Mapping[str, str]


def parse_source_tokens(raw: str) -> dict[str, str]:
    """Parse "source:token,source2:token2" into {source: token}."""
    tokens: dict[str, str] = {}
    for part in filter(None, (p.strip() for p in (raw or "").split(","))):
        source, sep, token = part.partition(":")
        source, token = source.strip(), token.strip()
        if not sep or not source or len(token) < MIN_TOKEN_LENGTH:
            raise ValueError(
                "INGEST_SOURCE_TOKENS entries must look like "
                f"'source:token' with a token of at least {MIN_TOKEN_LENGTH} characters"
            )
        if source in tokens:
            raise ValueError(f"INGEST_SOURCE_TOKENS lists source {source!r} twice")
        tokens[source] = token
    return tokens


class IngestTaskRequest(BaseModel):
    """SPEC 6.1a request body. Unknown fields are rejected before this runs."""

    model_config = ConfigDict(extra="forbid")

    source: str = Field(min_length=1, max_length=100)
    external_id: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=200)
    due_at: datetime | None = None
    priority: Literal["low", "normal", "high"] = "normal"
    created_at: datetime


_FIELDS = frozenset(IngestTaskRequest.model_fields)


def get_ingest_deps(request: Request) -> IngestDeps:
    """Resolve route dependencies from app state (set in the app lifespan)."""
    deps = getattr(request.app.state, "ingest_deps", None)
    if deps is None:
        raise HTTPException(status_code=503, detail="ingest is not configured")
    return deps


def _authenticate(authorization: str | None, source_tokens: Mapping[str, str]) -> str:
    """Return the source a valid bearer token belongs to, or raise 401."""
    unauthorized = HTTPException(
        status_code=401,
        detail="missing or invalid source token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not authorization:
        raise unauthorized
    scheme, _, presented = authorization.partition(" ")
    if scheme.lower() != "bearer" or not presented.strip():
        raise unauthorized
    presented = presented.strip()
    matched: str | None = None
    for source, token in source_tokens.items():  # check all: no early exit
        if hmac.compare_digest(presented.encode(), token.encode()):
            matched = source
    if matched is None:
        raise unauthorized
    return matched


@router.post(endpoints.HTTP_TASKS_INGEST)
async def ingest_task(
    request: Request,
    response: Response,
    deps: IngestDeps = Depends(get_ingest_deps),
) -> dict[str, Any]:
    """Accept one externally sourced task, idempotently."""
    token_source = _authenticate(
        request.headers.get("authorization"), deps.source_tokens
    )

    try:
        body = await request.json()
    except ValueError:
        raise HTTPException(status_code=400, detail="body must be valid JSON")
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="body must be a JSON object")
    unknown = sorted(set(body) - _FIELDS)
    if unknown:
        raise HTTPException(status_code=400, detail=f"unknown field(s): {unknown}")

    try:
        payload = IngestTaskRequest.model_validate(body)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=json.loads(exc.json()))

    if payload.source != token_source:
        # A valid token for source A must not write as source B.
        raise HTTPException(
            status_code=401,
            detail="token is not valid for this source",
            headers={"WWW-Authenticate": "Bearer"},
        )

    task, created = deps.store.ingest_task(
        source=payload.source,
        external_id=payload.external_id,
        title=payload.title,
        due_at=payload.due_at.isoformat() if payload.due_at else None,
        priority=payload.priority,
        created_at=payload.created_at.isoformat(),
    )
    response.status_code = 201 if created else 200
    logger.info(
        "[ingest] source=%s external_id=%s outcome=%s task_id=%s",
        payload.source, payload.external_id,
        "created" if created else "duplicate", task["task_id"],
    )
    return {
        "task_id": task["task_id"],
        "source": task["source"],
        "external_id": task["external_id"],
        "title": task["title"],
        "due_at": task["deadline"],
        "priority": task["priority"],
        "status": task["status"],
        "created_at": task["created_at"],
    }
