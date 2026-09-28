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
from typing import Any, cast

import httpx
from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.responses import HTMLResponse
from loguru import logger
from pipecat.serializers.vobiz import VobizFrameSerializer, parse_vobiz_start
from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketParams,
    FastAPIWebsocketTransport,
)
from pipecat.workers.runner import WorkerRunner

from voice_agent.config.languages import get_language_config
from voice_agent.config.settings import get_settings
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
app = FastAPI(title="Voice Agent Telephony API")
vobiz_client = VobizClient()

# Maps call_id -> WebSocket for graceful shutdown when the call ends
_active_websockets: dict[str, WebSocket] = {}


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


@app.get("/languages")
async def list_languages() -> dict[str, Any]:
    """List all supported languages for the frontend/CLI."""
    from voice_agent.config.languages import LANGUAGES

    return {
        "supported": [
            {"code": code, "name": cfg.name} for code, cfg in LANGUAGES.items()
        ],
        "default": "hi-IN",
    }


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
    from_number = str(form.get("From", "unknown"))
    to_number = str(form.get("To", "unknown"))

    language = resolve_language_for_inbound(to_number)

    host = request.headers.get("host", "")
    ws_url = f"wss://{host}/ws?language={language}&direction=inbound"

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
    {ws_url}
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
    to_number = body.get("to")
    language = body.get("language", "hi-IN")
    answer_url = body.get("answer_url")
    hangup_url = body.get("hangup_url")
    ring_url = body.get("ring_url")

    if not to_number or not answer_url:
        raise HTTPException(
            status_code=400,
            detail="'to' and 'answer_url' are required",
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
    ws_url = f"wss://{host}/ws?language={language}"

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
    {ws_url}
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

    # Register the call in Supabase and store the internal UUID
    try:
        supabase = SupabaseStore(settings.supabase_url, settings.supabase_service_key)
        internal_call_id = await supabase.create_call(
            call_uuid=call_id,
            direction=direction,
            from_number="",
            to_number="",
            language=language,
        )
        flow_manager.state["internal_call_id"] = internal_call_id
        logger.info(f"Supabase call record created: {internal_call_id}")
    except Exception as e:
        logger.error(f"Failed to create Supabase call record: {e}")
        flow_manager.state["internal_call_id"] = None

    lang_config = get_language_config(language)

    async def _start_flow() -> None:
        await asyncio.sleep(2.0)
        try:
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

        transcript_text = "\n".join(f"{m['role']}: {m['text']}" for m in messages)

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
