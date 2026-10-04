"""Pydantic response models for the read-only dashboard API.

Every endpoint in server.py that returns data must declare one of
these models as its response_model. FastAPI validates the return
value against the model and generates OpenAPI documentation from it,
so the frontend team has a single source of truth for the API
contract.

Why a separate module: the frontend developer reads this file to
learn the shapes without parsing route handlers. It is the API
contract, in code.
"""

from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


# ====== Response envelopes ======


class ApiResponse(BaseModel, Generic[T]):
    """Single-object response envelope.

    Every non-list endpoint returns this shape. The `success` flag
    lets the frontend branch on one field instead of checking HTTP
    status codes at every call site.
    """

    success: bool = True
    data: T


class PaginatedResponse(BaseModel, Generic[T]):
    """List response envelope with pagination metadata.

    `has_next` and `has_previous` are precomputed server-side so the
    frontend does not have to do arithmetic on `total`, `page`, and
    `limit` to decide whether to enable the Next/Previous buttons.
    That arithmetic is trivially easy to get wrong in JavaScript
    (off-by-one on the last page), so we do it once here.

    `total` is the full row count matching the filter, not the page
    size. The frontend uses it to render "Showing 1-20 of 347 calls".
    """

    success: bool = True
    data: list[T]
    total: int
    page: int
    limit: int
    has_next: bool
    has_previous: bool


class ErrorResponse(BaseModel):
    """Uniform error body for all non-2xx responses.

    FastAPI raises HTTPException with a `detail` field by default.
    We override the default handler to return this shape instead,
    so the frontend can parse errors with the same code path it uses
    for success responses.
    """

    success: bool = False
    error: str
    detail: str | None = None


# ====== Domain models ======


class CallSummary(BaseModel):
    """One row in the dashboard table.

    Deliberately narrow. The dashboard table needs exactly these
    fields and nothing more. If the frontend later needs `metrics`
    or `summary`, it fetches the detail endpoint for a specific row.

    Loading every column for every row would transfer the entire
    JSONB metrics blob (a few kilobytes per row) across the wire for
    a table that never displays it.
    """

    model_config = ConfigDict(from_attributes=True)

    call_uuid: str
    direction: str  # "inbound" | "outbound"
    from_number: str
    to_number: str
    language: str
    status: str
    started_at: datetime
    ended_at: datetime | None = None
    duration_seconds: int | None = None
    outcome: str | None = None
    recording_url: str | None = None


class TranscriptMessage(BaseModel):
    """One utterance in the call detail transcript view."""

    model_config = ConfigDict(from_attributes=True)

    role: str  # "user" | "assistant" | "system" | "tool"
    text: str
    created_at: datetime


class CallDetail(BaseModel):
    """Full detail for one call.

    Returned by GET /calls/{call_uuid}. Includes the transcript and
    the parsed AI summary. The `summary` field is typed as
    `dict[str, Any] | None` because the summary is stored as JSONB
    with a known shape (outcome, summary, next_action) but we do not
    want a malformed legacy row to cause a 500 on the detail
    endpoint. The frontend treats the parsed object as best-effort.
    """

    model_config = ConfigDict(from_attributes=True)

    call_uuid: str
    direction: str
    from_number: str
    to_number: str
    language: str
    status: str
    started_at: datetime
    answered_at: datetime | None = None
    ended_at: datetime | None = None
    duration_seconds: int | None = None
    outcome: str | None = None
    failure_reason: str | None = None
    consent_captured_at: datetime | None = None
    disclosure_version: str | None = None
    recording_url: str | None = None
    summary: dict[str, Any] | None = None
    messages: list[TranscriptMessage] = Field(default_factory=list)


class RecordingUrl(BaseModel):
    """Response for GET /calls/{call_uuid}/recording-url.

    Presigned URLs are time-limited. The frontend must fetch a fresh
    URL when the user clicks play, rather than caching the URL for
    the lifetime of the page.
    """

    url: str
    expires_in: int


class CallStats(BaseModel):
    """Dashboard counter cards.

    Four counters the dashboard renders at the top of the calls
    list. A single endpoint serves all four rather than four
    separate endpoints, because the four counts always need to be
    fetched together.
    """

    total: int
    completed: int
    failed: int
    in_progress: int


# ====== Phase 7.2: Agent configuration ======


class VoiceOverride(BaseModel):
    """Per-language TTS voice and STT locale overrides.

    Stored in agent_configs.voice_overrides as JSONB keyed by BCP-47
    code. Every field is optional: a language with no override uses
    the defaults from LanguageConfig.
    """

    model_config = ConfigDict(extra="forbid")

    tts_voice: str | None = None
    tts_language_code: str | None = None
    stt_locale: str | None = None


class AgentConfigPayload(BaseModel):
    """Request body for PUT /agents/config.

    extra='forbid' means an unknown field is a 422 instead of being
    silently ignored. That matters here: a typo like 'objectiv' would
    otherwise save silently and the operator would not learn until a
    call goes wrong.
    """

    model_config = ConfigDict(extra="forbid")

    agent_name: str = Field(min_length=1, max_length=64)
    company_name: str = Field(min_length=1, max_length=128)
    company_info: str = Field(default="", max_length=4000)
    objective: str = Field(min_length=1, max_length=1000)
    personality: str = Field(min_length=1, max_length=1000)
    greeting_template: str = Field(min_length=1, max_length=1000)
    max_call_duration_seconds: int = Field(default=600, ge=30, le=3600)
    primary_language: str = Field(min_length=2, max_length=10)
    supported_languages: list[str] = Field(min_length=1, max_length=10)
    voice_overrides: dict[str, VoiceOverride] = Field(default_factory=dict)


class AgentConfig(AgentConfigPayload):
    """Response model for GET /agents/config.

    Identical to the payload plus two server-added fields:
        - config_key: the singleton key. Always 'default' by the
        table's CHECK constraint. Included so the frontend can
        confirm it is reading the singleton row.
        - updated_at: when the row was last written.

    The write payload (AgentConfigPayload) does not include these
    because the client mmust not control them. A client that sent
    config_key='custom' would be silently rejected by the DB CHECK
    constraint, and one that sent updated_at would be able to
    falsify the audit trail.
    """

    config_key: str = "default"
    updated_at: datetime | None = None
