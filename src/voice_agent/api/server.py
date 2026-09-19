"""FastAPI server for Vobiz telephony integration.

Exposes:
    - GET  /health          : Health check
    - POST /call            : Trigger an outbound call
    - POST /answer          : VobizXML webhook — tells Vobiz where to stream audio
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

from voice_agent.config.settings import get_settings
from voice_agent.pipeline.agent_pipeline import create_agent_pipeline
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

    # Append language as query param so /answer can read it
    answer_with_lang = f"{answer_url}?language={language}"

    result = await vobiz_client.make_outbound_call(
        to_number=to_number,
        answer_url=answer_with_lang,
        hangup_url=hangup_url,
        ring_url=ring_url,
    )

    # Register the call in the state tracker
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

    # Build the WebSocket URL from the incoming Host header
    host = request.headers.get("host", "")
    ws_url = f"wss://{host}/ws?language={language}"

    # VobizXML: <Record> wraps <Stream> must be SIBLING elements, not nested.
    # <Record> must be self-closing and placed BEFORE <stream>.
    # This structure allows simultaneous recording and reall-time streaming.
    # `contentType="audio/x-mulaw;rate=8000"` matches standard telephony audio.
    # `keepCallAlive="true"` prevents Vobiz from hanging up when the stream
    # disconnects — it waits for the call to end naturally.
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
    """WebSocket endpoint for Vobiz Media Streams.

    Vobiz opens this connection after reading the VobizXML from /answer.
    Audio flows bidirectionally through the Pipecat pipeline.
    """
    await websocket.accept()
    logger.info("Vobiz WebSocket connection accepted")

    language = websocket.query_params.get("language", "hi-IN")
    logger.info(f"Starting pipeline in language: {language}")

    # Parse the Vobiz `start` event using the official parser.
    # IMPORTANT: parse_vobiz_start() returns a DICT, not an object.
    # Keys are snake_case: "stream_id", "call_id", "encoding", "sample_rate".
    try:
        parsed = await asyncio.wait_for(
            parse_vobiz_start(websocket),
            timeout=30.0,
        )
    except TimeoutError:
        logger.error("Time out waiting for Vobiz start event (30s)")
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

    logger.info(
        f"Vobiz stream started: streamId={stream_id}, "
        f"callId={call_id}, encoding={encoding}, sampleRate={sample_rate}"
    )

    # Build the VobizFrameSerializer from the parsed start event.
    # The serializer handles base64 decoding, byte order, resampling,
    # interruption signalling, and call teardown.
    # `sample_rate=None` tells the serializer to use its internal
    # stream resampler instead of assuming the wire rate equals the
    # pipeline rate.
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

    # CRITICAL: do NOT set audio_in_sample_rate or audio_out_sample_rate
    # on the transport params. The serializer negotiates the wire format
    # from the `start` event. The pipeline's output sample rate is set
    # separately on PipelineTask via create_agent_pipeline(audio_out_sample_rate=8000).
    transport = FastAPIWebsocketTransport(
        websocket=websocket,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            add_wav_header=False,  # CRITICAL: must be False for telephony
            serializer=serializer,
        ),
    )

    task = await create_agent_pipeline(
        transport=transport,
        language_code=language,
        audio_out_sample_rate=8000,  # Telephony output rate
    )

    try:
        runner = WorkerRunner()
        await runner.add_workers(task)
        await runner.run()
    except Exception as e:
        logger.error(f"Pipeline error: {e}")
    finally:
        # Vobiz does NOT send an inbound stop event.
        # The WebSocket close is the end-of-stream signal.
        # Flush per-call state here: generate summary, save transcript, etc.
        logger.info(f"Vobiz stream ended for call {call_id}")


@app.post("/hangup")
async def hangup_webhook(request: Request) -> dict[str, Any]:
    """Authoritative end-of-call signal from Vobiz.

    Detects failure statuses (busy, no-answer, failed, timeout, cancel)
    and marks the call state accordingly.
    """
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

    return {"status": "received"}


@app.post("/recording-ready")
async def recording_ready(request: Request) -> dict[str, Any]:
    """Vobiz calls this when the recording file is ready.

    Contains RecordUrl, RecordingID, RecordingDuration, CallUUID.
    """
    body = await request.form()
    logger.info(f"Recording ready: {dict(body)}")
    # In Part 3, download and store the recording in Supabase Storage
    return {"status": "received"}
