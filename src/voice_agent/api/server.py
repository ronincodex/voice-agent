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
from voice_agent.pipeline.agent_pipeline import create_agent_pipeline
from voice_agent.pipeline.nodes import build_initial_node
from voice_agent.telephony.call_state import (
    CallStatus,
    get_call,
    list_active_calls,
    register_call,
    remove_call,
)
from voice_agent.telephony.client import VobizClient

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
    <Record action="https://{host}/recording-ready" method="POST"
    recordSession="true" redirect="false" maxLength="3600" playBeep="false"/>
    <Stream bidirectional="true" keepCallAlive="true"
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
    method="POST"
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


@app.post("/hangup")
async def hangup_webhook(request: Request) -> dict[str, Any]:
    """Authoritative end-of-call signal from Vobiz."""
    body = await request.form()
    call_uuid = str(body.get("CallUUID", "unknown"))
    hangup_cause = str(body.get("HangupCause", ""))
    hangup_cause_name = str(body.get("HangupCauseName", ""))
    call_status = str(body.get("CallStatus", "completed"))

    logger.info(
        f"Hangup callback: CallUUID={call_uuid}, "
        f"status={call_status}, cause={hangup_cause_name}"
    )

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

        ws = _active_websockets.pop(call_uuid, None)
        if ws is not None:
            try:
                await ws.close(code=1000)
                logger.info(f"Closed WebSocket for call {call_uuid}")
            except Exception as e:
                logger.warning(f"Failed to close WebSocket: {e}")

    return {"status": "received"}


@app.post("/recording-ready")
async def recording_ready(request: Request) -> dict[str, Any]:
    """Vobiz calls this when the recording file is ready.

    Contains RecordUrl, RecordingID, RecordingDuration, CallUUID.
    """
    body = await request.form()
    logger.info(f"Recording ready: {dict(body)}")
    return {"status": "received"}
