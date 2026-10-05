"""FastAPI server for Vobiz telephony integration.

Exposes:
    - GET  /health          : Health check
    - POST /call            : Trigger an outbound call
    - POST /answer          : VobizXML webhook — tells Vobiz where to stream audio
    - POST /incoming        : VobizXML webhook — inbound call handling
    - POST /hangup          : Call hangup webhook (authoritative end-of-call signal)
    - WS   /ws              : WebSocket endpoint for Vobiz Media Streams
    - POST /recording-ready : Recording callback from Vobiz
"""

import asyncio
from datetime import UTC, datetime
from html import escape as xml_escape
from typing import Any, cast
from urllib.parse import quote

import httpx
from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from loguru import logger
from pipecat.serializers.vobiz import VobizFrameSerializer, parse_vobiz_start
from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketParams,
    FastAPIWebsocketTransport,
)
from pipecat.workers.runner import WorkerRunner

from voice_agent.api.schemas import (
    AgentConfig,
    AgentConfigPayload,
    ApiResponse,
    CallDetail,
    CallStats,
    CallSummary,
    PaginatedResponse,
    RecordingUrl,
)
from voice_agent.compliance.calling_window import (
    current_ist_time,
    is_within_calling_window,
)
from voice_agent.compliance.pii import detect_and_mask
from voice_agent.config.settings import get_settings
from voice_agent.db.agent_config import AgentConfigStore, invalidate_config_cache
from voice_agent.db.audit import AuditTrail
from voice_agent.db.supabase_client import SupabaseStore
from voice_agent.observability.logging_config import (
    bind_call_context,
    configure_logging,
    unbind_call_context,
)
from voice_agent.observability.retry import retry_standard
from voice_agent.pipeline.agent_pipeline import create_agent_pipeline
from voice_agent.pipeline.nodes import build_initial_node
from voice_agent.postcall.summarizer import generate_summary
from voice_agent.storage.r2_client import R2Storage
from voice_agent.telephony.call_state import (
    CallStatus,
    get_call,
    list_active_calls,
    register_call,
    remove_call,
)
from voice_agent.telephony.client import VobizClient

configure_logging(level="DEBUG")

settings = get_settings()

if settings.bypass_calling_hours:
    logger.warning(
        "BYPASS_CALLING_HOURS=true: TRAI calling-hour enforcement is DISABLED. "
        "This must be false in production."
    )
app = FastAPI(title="Voice Agent Telephony API")

# CORS: allow the frontend origin to make cross-origin requests.
# Only the origin from settings is allowed, never "*". A wildcard
# combined with allow_credentials=True is rejected by browsers
# anyway, and a wildcard without credentials would let any site
# call the API. The explicit origin is both safer and correct.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

vobiz_client = VobizClient()

# Maps call_id -> WebSocket for graceful shutdown when the call ends
_active_websockets: dict[str, WebSocket] = {}


def _normalize_phone(number: str) -> str:
    """Return the number in E.164 form with a leading +.

    Vobiz webhooks strip the '+' from caller IDs. Normalize at every
    boundary so the opt-out table, audit trail, and outbound API calls
    all see the same canonical form.
    """
    digits = number.strip().replace(" ", "").replace("-", "")
    if not digits:
        return ""
    if digits.startswith("+"):
        return digits
    # India: bare 10-digit mobile
    if len(digits) == 10 and digits[0] in "6789":
        return f"+91{digits}"
    # India with 91 prefix
    if digits.startswith("91") and len(digits) == 12:
        return f"+{digits}"
    return f"+{digits}"


@app.on_event("startup")
async def start_call_timeout_monitor() -> None:
    """Background task to clean up stale calls."""

    async def monitor() -> None:
        while True:
            await asyncio.sleep(60)
            now = datetime.now(UTC)
            for state in list(list_active_calls()):
                age = (now - state.created_at).total_seconds()
                if state.status in ("initiated", "ringing") and age > 120:
                    state.mark_ended("timeout", "No answer within 120s")
                    logger.warning(f"Call {state.call_uuid} timed out after {age:.0f}s")
                elif age > 3600:
                    remove_call(state.call_uuid)

    asyncio.create_task(monitor())


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "ok"}


# ====== Phase 7.1: Dashboard read endpoints ======


@app.get(
    "/calls",
    response_model=PaginatedResponse[CallSummary],
    tags=["dashboard"],
)
async def list_calls(
    page: int = 1,
    limit: int = 20,
    direction: str | None = None,
    status: str | None = None,
    language: str | None = None,
) -> PaginatedResponse[CallSummary]:
    """Return a paginated, filterable list of calls.

    Query parameters:
        page      : 1-based page number. Default 1.
        limit     : Rows per page, 1–100. Default 20.
        direction : "inbound" or "outbound". Optional.
        status    : "completed" / "failed" / "busy" / etc. Optional.
        language  : BCP-47 code, e.g. "hi-IN". Optional.

    Sorted by started_at descending (newest first).
    """
    # Clamp limit. Anything above 100 risks a slow response and a
    # large payload; the dashboard never needs more than 100 rows.
    limit = max(1, min(limit, 100))
    page = max(1, page)

    store = SupabaseStore(settings.supabase_url, settings.supabase_service_key)
    rows, total = await store.list_calls(
        page=page,
        limit=limit,
        direction=direction,
        status=status,
        language=language,
    )

    summaries = [CallSummary.model_validate(row) for row in rows]
    has_next = page * limit < total
    has_previous = page > 1

    return PaginatedResponse[CallSummary](
        data=summaries,
        total=total,
        page=page,
        limit=limit,
        has_next=has_next,
        has_previous=has_previous,
    )


@app.get(
    "/calls/stats",
    response_model=ApiResponse[CallStats],
    tags=["dashboard"],
)
async def call_stats() -> ApiResponse[CallStats]:
    """Return the four counter values for the dashboard cards."""
    store = SupabaseStore(settings.supabase_url, settings.supabase_service_key)
    counts = await store.get_call_counts()
    return ApiResponse[CallStats](data=CallStats(**counts))


@app.get(
    "/calls/{call_uuid}",
    response_model=ApiResponse[CallDetail],
    tags=["dashboard"],
)
async def get_call_detail_route(call_uuid: str) -> ApiResponse[CallDetail]:
    """Return one call with full transcript and AI summary."""
    store = SupabaseStore(settings.supabase_url, settings.supabase_service_key)
    call = await store.get_call_detail(call_uuid)
    if call is None:
        raise HTTPException(status_code=404, detail=f"Call {call_uuid} not found")
    return ApiResponse[CallDetail](data=CallDetail.model_validate(call))


@app.get(
    "/calls/{call_uuid}/recording-url",
    response_model=ApiResponse[RecordingUrl],
    tags=["dashboard"],
)
async def get_recording_url(call_uuid: str) -> ApiResponse[RecordingUrl]:
    """Return a presigned URL for the call's recording.

    Presigned URLs expire. The frontend should fetch a fresh one on
    every play action rather than caching the URL in component state.
    The URL is generated against the R2 key already stored in the
    calls.recording_url column, not against a public bucket path.
    """
    store = SupabaseStore(settings.supabase_url, settings.supabase_service_key)
    call = await store.get_call_by_uuid(call_uuid)
    if call is None:
        raise HTTPException(status_code=404, detail=f"Call {call_uuid} not found")
    r2_key = call.get("recording_url")
    if not r2_key:
        raise HTTPException(
            status_code=404,
            detail=f"No recording available for call {call_uuid}",
        )

    r2 = R2Storage(
        account_id=settings.r2_account_id,
        access_key_id=settings.r2_access_key_id,
        secret_access_key=settings.r2_secret_access_key,
        bucket_name=settings.r2_bucket_name,
    )
    url = r2.generate_presigned_url(r2_key, expires_in=3600)
    return ApiResponse[RecordingUrl](
        data=RecordingUrl(url=url, expires_in=3600),
    )


# ====== Phase 7.2: Agent configuration ======


@app.get(
    "/agents/config",
    response_model=ApiResponse[AgentConfig],
    tags=["agents"],
)
async def get_agent_config() -> ApiResponse[AgentConfig]:
    """Return the current agent configuration.

    The cache is shared with the call pipeline (see agent_config.py),
    so a GET immediately after a PUT may still serve the previous
    value if the process that handled the PUT is not the one serving
    this request. Invalidating on write makes that window one cache
    lifetime at most, and in a single-process deployment the window
    is zero.
    """
    store = AgentConfigStore(settings.supabase_url, settings.supabase_service_key)
    row = await store.get(use_cache=False)
    return ApiResponse[AgentConfig](data=AgentConfig.model_validate(row))


@app.put(
    "/agents/config",
    response_model=ApiResponse[AgentConfig],
    tags=["agents"],
)
async def update_agent_config(
    payload: AgentConfigPayload,
) -> ApiResponse[AgentConfig]:
    """Replace the agent configuration.

    PUT semantics: the body is the full replacement, not a patch.
    Missing optional fields are reset to their defaults. Use PATCH
    if you later need partial updates.

    Validation:
      - Every language in supported_languages must exist in the
        LanguageConfig registry, so a typo cannot produce a call in
        a language the pipeline cannot speak.
      - primary_language must appear in supported_languages.
      - Every key in voice_overrides must also be a supported
        language.
    """
    from voice_agent.config.languages import LANGUAGES

    unknown = [c for c in payload.supported_languages if c not in LANGUAGES]
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Unsupported language codes: {unknown}. "
                f"Supported: {sorted(LANGUAGES.keys())}"
            ),
        )
    if payload.primary_language not in payload.supported_languages:
        raise HTTPException(
            status_code=422,
            detail=(
                f"primary_language {payload.primary_language!r} must be "
                f"present in supported_languages"
            ),
        )
    bad_override_keys = [
        k for k in payload.voice_overrides if k not in payload.supported_languages
    ]
    if bad_override_keys:
        raise HTTPException(
            status_code=422,
            detail=(
                f"voice_overrides keys must be supported languages. "
                f"Unexpected: {bad_override_keys}"
            ),
        )

    store = AgentConfigStore(settings.supabase_url, settings.supabase_service_key)
    row = await store.upsert(payload.model_dump())
    invalidate_config_cache()
    return ApiResponse[AgentConfig](data=AgentConfig.model_validate(row))


@app.get("/languages", response_model=ApiResponse[dict[str, Any]])
async def list_languages() -> ApiResponse[dict[str, Any]]:
    """List all supported languages.

    Wrapped in the ApiResponse envelope so fetchApi<T> works
    uniformly across every read endpoint. This handler predated
    the Phase 7.1 envelope convention; Phase 7.7 brings it into
    alignment. No other consumer existed.
    """
    from voice_agent.config.languages import LANGUAGES

    return ApiResponse[dict[str, Any]](
        data={
            "supported": [
                {"code": code, "name": cfg.name} for code, cfg in LANGUAGES.items()
            ],
            "default": "hi-IN",
        }
    )


def resolve_language_for_inbound(dialed_number: str) -> str:
    """Map the dialed number (DNIS) to a language.

    In production this queries a `phone_numbers` table.
    For the prototype, use an in-memory mapping.
    """
    DNIS_MAP = {
        "+91XXXXXXXXXX": "hi-IN",
        "+91YYYYYYYYYY": "en-IN",
        "+91ZZZZZZZZZZ": "ta-IN",
    }
    return DNIS_MAP.get(dialed_number, "hi-IN")


@app.post("/incoming")
async def incoming_webhook(request: Request) -> HTMLResponse:
    """Vobiz fetches this when an inbound call arrives.

    Returns VobizXML that records the call and opens a WebSocket.
    """
    form = await request.form()
    from_number = _normalize_phone(str(form.get("From", "")))
    to_number = _normalize_phone(str(form.get("To", "")))

    language = resolve_language_for_inbound(to_number)

    host = request.headers.get("host", "")
    # Carry from, to, and direction into the WebSocket query string so
    # the handler can populate calls. from_number and calls. to_number.
    # Previously both were hardcoded to "" in create_call.
    ws_url = (
        f"wss://{host}/ws?"
        f"language={language}"
        f"&direction=inbound"
        f"&from={quote(from_number, safe='')}"
        f"&to={quote(to_number, safe='')}"
    )

    # XML text content requires & to be escaped as &amp;. Vobiz's
    # parser rejects the VobizXML otherwise (HangupCause: Invalid
    # Answer XML).
    ws_url_xml = xml_escape(ws_url)

    vobiz_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
    <Response>
    <Record action="https://{host}/recording-ready"
    callbackUrl="https://{host}/recording-complete"
    method="POST"
    callbackMethod="POST"
    recordSession="true"
    redirect="false"
    maxLength="3600"
    playBeep="false"/>
    <Stream bidirectional="true"
    keepCallAlive="true"
    contentType="audio/x-mulaw;rate=8000">
    {ws_url_xml}
    </Stream>
    </Response>"""
    logger.info(
        f"Inbound call: from={from_number}, to={to_number}, language={language}"
    )
    return HTMLResponse(content=vobiz_xml, media_type="application/xml")


@app.post("/ring")
async def ring_webhook(request: Request) -> dict[str, Any]:
    """Vobiz sends 'ringing' status here."""
    body = await request.form()
    call_uuid = str(body.get("CallUUID", "unknown"))
    logger.info(f"Call {call_uuid} is ringing")

    state = get_call(call_uuid)
    if state:
        state.mark_ringing()

    return {"status": "received"}


@app.post("/call")
async def trigger_call(request: Request) -> dict[str, Any]:
    """Trigger an outbound call.

    Body (JSON):
        {
        "to": "+91XXXXXXXXXX",
        "language": "hi-IN",
        "answer_url": "https://ngrok-free.app",
        "hangup_url": "https://ngrok-free.app"
        }
    """
    body = await request.json()
    to_number = _normalize_phone(str(body.get("to", "")))
    language = body.get("language", "hi-IN")
    answer_url = body.get("answer_url")
    hangup_url = body.get("hangup_url")
    ring_url = body.get("ring_url")

    # Phase 7.7: the frontend sends only {to, language}. The
    # callback URLs are derived from the configured public base
    # URL, so the ngrok or Render host lives in one place.
    # Explicit URLs in the request body still win, keeping the
    # existing curl-based workflow working unchanged.
    if not answer_url and settings.public_base_url:
        base = settings.public_base_url.rstrip("/")
        answer_url = f"{base}/answer"
        hangup_url = hangup_url or f"{base}/hangup"
        ring_url = ring_url or f"{base}/ring"

    if not to_number or not answer_url:
        raise HTTPException(
            status_code=400,
            detail=(
                "'to' is required, and either 'answer_url' must be sent "
                "in the request or PUBLIC_BASE_URL must be set on the "
                "server"
            ),
        )

    placeholder_markers = ("YOUR-NGROK", "your-ngrok", "example.com", "<")
    for field_name, field_value in (
        ("answer_url", answer_url),
        ("hangup_url", hangup_url),
        ("ring_url", ring_url),
    ):
        if field_value and any(m in field_value for m in placeholder_markers):
            raise HTTPException(
                status_code=400,
                detail=f"'{field_name}' contains a placeholder URL: {field_value}",
            )

    # ---- Phase 5.7.3: TRAI calling-hour gate ----
    now = datetime.now(UTC)
    if not settings.bypass_calling_hours and not is_within_calling_window(now):
        ist_time = current_ist_time(now)
        logger.warning(
            f"Call to {to_number} blocked: outside 9 AM - 8:45 PM IST "
            f"(IST now {ist_time})"
        )
        try:
            audit = AuditTrail(settings.supabase_url, settings.supabase_service_key)
            await audit.record(
                to_number,
                "calling_hours_blocked",
                {"ist_time": ist_time, "attempted_to": to_number},
            )
        except Exception as e:
            logger.error(f"Failed to audit calling-hour block: {e}")
        raise HTTPException(
            status_code=400,
            detail=(
                f"Outside TRAI calling window (9 AM - 9 PM IST). IST now: {ist_time}"
            ),
        )

    # ---- Phase 5.7.3: local opt-out gate ----
    supabase_gate = SupabaseStore(settings.supabase_url, settings.supabase_service_key)
    if await supabase_gate.check_opt_out(to_number):
        logger.warning(f"Call to {to_number} blocked: on local opt-out list")
        try:
            audit = AuditTrail(settings.supabase_url, settings.supabase_service_key)
            await audit.record(
                to_number,
                "dnd_blocked",
                {"source": "local_optout", "attempted_to": to_number},
            )
        except Exception as e:
            logger.error(f"Failed to audit opt-out block: {e}")
        raise HTTPException(
            status_code=400,
            detail=(
                "This number has requested no further contact. "
                "Call blocked per TRAI TCCCPR."
            ),
        )

    answer_with_lang = f"{answer_url}?language={language}"

    result = await vobiz_client.make_outbound_call(
        to_number=to_number,
        answer_url=answer_with_lang,
        hangup_url=hangup_url,
        ring_url=ring_url,
    )

    call_uuid = result.get("request_uuid", "unknown")
    register_call(call_uuid, to_number, language)
    logger.info(f"Registered call {call_uuid} for tracking")

    return {"status": "initiated", "vobiz_response": result}


@app.post("/answer")
async def answer_webhook(request: Request) -> HTMLResponse:
    """Vobiz fetches this URL after the call connects.

    We respond with VobizXML that tells Vobiz to:
        1. Record the call to a file.
        2. Open a bidirectional WebSocket to our /ws endpoint.
    """
    form = await request.form()
    call_uuid = str(form.get("CallUUID", "unknown"))
    language = request.query_params.get("language", "hi-IN")

    logger.info(f"VobizXML requested for call {call_uuid}, language={language}")

    state = get_call(call_uuid)
    if state:
        state.mark_answered()
    host = request.headers.get("host", "")
    # For outbound calls the "from" is our Vobiz number. Vobiz may
    # not include a From field on the answer webhook, so fall back to
    # the configured number.
    from_number = _normalize_phone(str(form.get("From", settings.vobiz_phone_number)))
    to_number = _normalize_phone(str(form.get("To", "")))
    ws_url = (
        f"wss://{host}/ws?"
        f"language={language}"
        f"&direction=outbound"
        f"&from={quote(from_number, safe='')}"
        f"&to={quote(to_number, safe='')}"
    )
    ws_url_xml = xml_escape(ws_url)

    vobiz_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
    <Response>
    <Record action="https://{host}/recording-ready"
    callbackUrl="https://{host}/recording-complete"
    method="POST"
    callbackMethod="POST"
    recordSession="true"
    redirect="false"
    maxLength="3600"
    playBeep="false"/>
    <Stream bidirectional="true"
    keepCallAlive="true"
    contentType="audio/x-mulaw;rate=8000">
    {ws_url_xml}
    </Stream>
    </Response>"""
    return HTMLResponse(content=vobiz_xml, media_type="application/xml")


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """WebSocket endpoint for Vobiz Media Streams."""
    await websocket.accept()

    logger.info("Vobiz WebSocket connection accepted")

    language = websocket.query_params.get("language", "hi-IN")
    direction = websocket.query_params.get("direction", "outbound")
    from_number = websocket.query_params.get("from", "")
    to_number = websocket.query_params.get("to", "")
    logger.info(f"WebSocket connected: language={language}, direction={direction}")

    # Parse the Vobiz `start` event. parse_vobiz_start() returns a DICT.
    try:
        parsed = await asyncio.wait_for(
            parse_vobiz_start(websocket),
            timeout=30.0,
        )
    except TimeoutError:
        logger.error("Timeout waiting for Vobiz start event (30s)")
        await websocket.close()
        return
    except Exception as e:
        logger.error(f"Failed to parse Vobiz start event: {e}")
        await websocket.close()
        return

    stream_id = parsed["stream_id"]
    call_id = parsed["call_id"]
    encoding = parsed["encoding"]
    sample_rate = parsed["sample_rate"]

    # Bind call_id to every log line in this coroutine and its children
    bind_call_context(call_id)

    _active_websockets[call_id] = websocket

    logger.info(
        f"Vobiz stream started: streamId={stream_id}, "
        f"callId={call_id}, encoding={encoding}, sampleRate={sample_rate}"
    )

    serializer = VobizFrameSerializer(
        stream_id=stream_id,
        call_id=call_id,
        auth_id=settings.vobiz_auth_id,
        auth_token=settings.vobiz_auth_token,
        params=VobizFrameSerializer.InputParams(
            vobiz_sample_rate=sample_rate,
            encoding=encoding,
            sample_rate=None,
            l16_byte_order="be",
            auto_hang_up=True,
        ),
    )

    transport = FastAPIWebsocketTransport(
        websocket=websocket,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            audio_in_sample_rate=16000,  # Force 16kHz input for Smart Turn v3
            add_wav_header=False,
            serializer=serializer,
        ),
    )

    task, flow_manager = await create_agent_pipeline(
        transport=transport,
        language_code=language,
        audio_out_sample_rate=8000,
        call_id=call_id,
    )
    flow_manager.state["to_number"] = to_number

    # Register the call in Supabase and store the internal UUID
    try:
        supabase = SupabaseStore(settings.supabase_url, settings.supabase_service_key)
        internal_call_id = await supabase.create_call(
            call_uuid=call_id,
            direction=direction,
            from_number=from_number,
            to_number=to_number,
            language=language,
        )
        flow_manager.state["internal_call_id"] = internal_call_id
        logger.info(f"Supabase call record created: {internal_call_id}")
    except Exception as e:
        logger.error(f"Failed to create Supabase call record: {e}")
        flow_manager.state["internal_call_id"] = None

    # lang_config = get_language_config(language)

    async def _start_flow() -> None:
        await asyncio.sleep(2.0)
        try:
            # Read the overridden config from flow_manager.state.
            # create_agent_pipeline applies the Phase 7.2 agent
            # config (agent_name, greeting_template, personality,
            # objective, voice_overrides) to its local lang_config
            # and stores the result in state["lang_config"].
            # Calling get_language_config(language) here instead
            # would return the base language config WITHOUT those
            # overrides, and the greeting node would speak the
            # default persona name regardless of what PUT
            # /agents/config wrote.
            lang_config = flow_manager.state["lang_config"]
            await flow_manager.initialize(build_initial_node(lang_config))
            logger.info(f"Flow initialized for call {call_id}")
        except Exception as e:
            logger.error(f"Flow initialization failed: {e}")

    asyncio.create_task(_start_flow())

    try:
        runner = WorkerRunner()
        await runner.add_workers(task)
        await runner.run()
    except Exception as e:
        logger.error(f"Pipeline error: {e}")
    finally:
        _active_websockets.pop(call_id, None)
        logger.info(f"Vobiz stream ended for call {call_id}")

        # Persist latency metrics collected during the call
        collector = flow_manager.state.get("metrics_collector")
        if collector is not None:
            try:
                summary_metrics = collector.aggregate()
                if summary_metrics:
                    supabase = SupabaseStore(
                        settings.supabase_url, settings.supabase_service_key
                    )
                    await supabase.update_call(call_id, metrics=summary_metrics)
                    logger.info(
                        f"Metrics persisted for {call_id}: "
                        f"{list(summary_metrics.keys())}"
                    )
            except Exception as e:
                logger.error(f"Failed to persist metrics for {call_id}: {e}")

        # Phase 5.7.5: persist prompt injection guard count if any
        guard = flow_manager.state.get("prompt_injection_guard")
        if guard is not None and guard.flagged_count > 0:
            try:
                audit = AuditTrail(settings.supabase_url, settings.supabase_service_key)
                await audit.record(
                    call_id,
                    "guardrail_prompt_injection",
                    {"count": guard.flagged_count},
                )
                logger.info(
                    f"Prompt injection blocked {guard.flagged_count}x "
                    f"for call {call_id}"
                )
            except Exception as e:
                logger.error(f"Failed to record guardrail audit for {call_id}: {e}")

        # Fire-and-forget summary generation from the persisted transcript
        persisted_call_id = flow_manager.state.get("internal_call_id")
        if persisted_call_id:
            asyncio.create_task(
                _generate_and_persist_summary(call_id, persisted_call_id)
            )

        # Clear context after all dependent tasks have been scheduled
        unbind_call_context()


async def _generate_and_persist_summary(
    call_uuid: str,
    internal_call_id: str,
) -> None:
    """Fetch transcript, generate AI summary, persist to Supabase.

    Runs as a fire-and-forget task. All errors are logged but never raised.
    """
    try:
        supabase = SupabaseStore(settings.supabase_url, settings.supabase_service_key)
        messages = await supabase.get_transcript(internal_call_id)

        if not messages:
            logger.warning(f"No transcript for call {call_uuid}, skipping summary")
            return

        # ---- Phase 5.7.4: PII masking ----
        # Concatenate adjacent same-role messages with a space before
        # running detection. STT splits long utterances across multiple
        # frames (e.g. a phone number split into "98765" + "43210"), so
        # per-message detection misses PII that spans the boundary.
        # Detection runs on the joined text; the masked result is stored
        # as a single consolidated message per role.
        user_concat = " ".join(m["text"] for m in messages if m["role"] == "user")
        assistant_concat = " ".join(
            m["text"] for m in messages if m["role"] == "assistant"
        )

        masked_user, user_counts = detect_and_mask(user_concat)
        masked_assistant, assistant_counts = detect_and_mask(assistant_concat)

        mask_counts: dict[str, int] = {
            k: user_counts.get(k, 0) + assistant_counts.get(k, 0)
            for k in {**user_counts, **assistant_counts}
        }

        if mask_counts:
            # Replace the per-utterance transcript with one masked row per
            # role. Atomic: the Postgres function deletes and inserts in
            # a single transaction, so a partial failure cannot leave the
            # call without a transcript. Plaintext never persists.
            rows: list[dict[str, str]] = []
            if masked_user:
                rows.append({"role": "user", "text": masked_user})
            if masked_assistant:
                rows.append({"role": "assistant", "text": masked_assistant})

            supabase._client.rpc(
                "replace_call_messages",
                {"p_call_id": internal_call_id, "p_messages": rows},
            ).execute()

            audit = AuditTrail(settings.supabase_url, settings.supabase_service_key)
            await audit.record(call_uuid, "pii_masked", {"counts": mask_counts})
            logger.info(f"PII masked for {call_uuid}: {mask_counts}")

        # The summary sees the fully masked transcript.
        transcript_text = f"user: {masked_user}\nassistant: {masked_assistant}"

        summary = await generate_summary(
            api_key=settings.sarvam_api_key,
            transcript=transcript_text,
            groq_api_key=settings.groq_api_key,
            groq_model=settings.groq_llm_model,
            enable_fallback=settings.enable_fallback_summarizer,
        )

        await supabase.update_call(
            call_uuid,
            summary=summary,
            outcome=summary.get("outcome", "other"),
        )
        logger.info(
            f"Summary persisted for {call_uuid}: outcome={summary.get('outcome')}"
        )
    except Exception as e:
        logger.error(f"Summary generation failed for {call_uuid}: {e}")


@app.post("/hangup")
async def hangup_webhook(request: Request) -> dict[str, Any]:
    """Authoritative end-of-call signal from Vobiz.

    Marks the call state, persists to Supabase, and closes the WebSocket.
    """
    body = await request.form()
    call_uuid = str(body.get("CallUUID", "unknown"))
    duration = int(str(body.get("Duration", "0")))
    call_status = str(body.get("CallStatus", "completed"))
    hangup_cause = str(body.get("HangupCause", ""))
    hangup_cause_name = str(body.get("HangupCauseName", ""))

    logger.info(
        f"Hangup callback: CallUUID={call_uuid}, "
        f"status={call_status}, cause={hangup_cause_name}, duration={duration}s"
    )

    # 1. Update in-memory state
    state = get_call(call_uuid)
    if state:
        FAILURE_STATUSES: tuple[str, ...] = (
            "no-answer",
            "busy",
            "failed",
            "timeout",
            "cancel",
        )
        if call_status in FAILURE_STATUSES:
            state.mark_ended(cast(CallStatus, call_status), hangup_cause_name)
            logger.error(
                f"Call {call_uuid} FAILED: status={call_status}, "
                f"cause={hangup_cause_name}, raw_cause={hangup_cause}"
            )
        else:
            state.mark_ended("completed")
            logger.info(f"Call {call_uuid} completed normally")

    # 2. Persist to Supabase (failure does not block cleanup)
    try:
        supabase = SupabaseStore(settings.supabase_url, settings.supabase_service_key)
        await supabase.update_call(
            call_uuid,
            status=call_status,
            ended_at=datetime.now(UTC).isoformat(),
            duration_seconds=duration,
        )
        logger.info(f"Call {call_uuid} persisted to Supabase")
    except Exception as e:
        logger.error(f"Failed to persist call {call_uuid} to Supabase: {e}")

    # 3. Close WebSocket (always, regardless of Supabase outcome)
    ws = _active_websockets.pop(call_uuid, None)
    if ws is not None:
        try:
            await ws.close(code=1000)
            logger.info(f"Closed WebSocket for call {call_uuid}")
        except Exception as e:
            logger.debug(f"Failed to close WebSocket: {e}")

    return {"status": "received"}


@app.post("/recording-ready")
async def recording_ready(request: Request) -> dict[str, Any]:
    """Vobiz fires this when recording STARTS (premature).

    Do not attempt to download here - the file does not exist yet.
    The /recording-complete callbackUrl fires when the file is ready.
    """
    body = await request.form()
    call_uuid = str(body.get("CallUUID", "unknown"))
    logger.info(
        f"Recording started for {call_uuid} "
        f"(status={body.get('CallStatus')}, "
        f"duration={body.get('RecordingDuration')}); awaiting completion"
    )
    return {"status": "received"}


@app.post("/recording-complete")
async def recording_complete(request: Request) -> dict[str, Any]:
    """Vobiz fires this when the recording MP3 file is ready.

    Uses the Vobiz Recording API to fetch the authenticated download URL,
    then downloads and uploads to R2.
    """

    body = await request.form()
    call_uuid = str(body.get("CallUUID", "unknown"))
    recording_id = str(body.get("RecordingID", ""))

    logger.info(f"Recording complete: call={call_uuid}, recording_id={recording_id}")

    if recording_id and call_uuid != "unknown":
        asyncio.create_task(_process_recording_complete(call_uuid, recording_id))
    else:
        logger.warning("Recording complete: missing CallUUID or RecordingID")

    return {"status": "received"}


@retry_standard
async def _process_recording_complete(
    call_uuid: str,
    recording_id: str,
) -> None:
    """Fetch authenticated recording URL, download, upload to R2, persist."""
    try:
        # 1. Fetch the real, authenticated recording_url from Vobiz API
        metadata_url = (
            f"https://api.vobiz.ai/api/v1/Account/"
            f"{settings.vobiz_auth_id}/Recording/{recording_id}/"
        )
        async with httpx.AsyncClient(timeout=30.0) as client:
            meta_resp = await client.get(
                metadata_url,
                headers={
                    "X-Auth-ID": settings.vobiz_auth_id,
                    "X-Auth-Token": settings.vobiz_auth_token,
                },
            )
            meta_resp.raise_for_status()
            metadata = meta_resp.json()

        real_url = metadata.get("recording_url")
        if not real_url:
            logger.error(f"Vobiz API returned no recording_url for {recording_id}")
            return

        logger.info(f"Vobiz real recording_url: {real_url}")

        # 2. Download the actual MP3 with auth headers
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(
                real_url,
                headers={
                    "X-Auth-ID": settings.vobiz_auth_id,
                    "X-Auth-Token": settings.vobiz_auth_token,
                },
            )
            resp.raise_for_status()
            audio_bytes = resp.content

        logger.info(f"Downloaded recording for {call_uuid}: {len(audio_bytes)} bytes")

        # 3. Upload to R2
        r2 = R2Storage(
            account_id=settings.r2_account_id,
            access_key_id=settings.r2_access_key_id,
            secret_access_key=settings.r2_secret_access_key,
            bucket_name=settings.r2_bucket_name,
        )
        key = await r2.upload_recording(call_uuid, audio_bytes)

        # 4. Persist to Supabase
        supabase = SupabaseStore(settings.supabase_url, settings.supabase_service_key)
        await supabase.update_call(call_uuid, recording_url=key)
        logger.info(f"Recording pipeline complete for {call_uuid} -> {key}")

    except Exception as e:
        logger.error(
            f"Recording pipeline failed for {call_uuid} "
            f"(recording_id={recording_id}): {e}"
        )
