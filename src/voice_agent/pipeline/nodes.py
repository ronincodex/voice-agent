"""Pipecat Flows node definitions for the voice agent.

Each node is a conversation phase with:
    - A scoped role_message (persona + language rules)
    - Scoped task_messages (what to do in this phase)
    - A scoped functions list (which tools the LLM may call)

Transitions are deterministic: handlers return (result, next_node).

Phase graph:
    greeting -> qualify -> confirm -> closing -> [terminate]
"""

from typing import Any

from loguru import logger
from pipecat.flows import FlowManager, NodeConfig

from voice_agent.config.languages import LanguageConfig
from voice_agent.observability.idempotency import idempotent_tool
from voice_agent.pipeline.validators import (
    is_affirmative_reply,
    is_busy_response,
    is_explicit_goodbye,
    is_wrong_number,
)


# ====== Shared helpers ======
def _get_session_state(flow_manager: FlowManager) -> Any:
    """Return the shared CallSessionState, or None if missing."""
    return flow_manager.state.get("session_state")


def _lang_block(lang_config: LanguageConfig) -> str:
    """Return the language-specific instruction block for the LLM."""
    return lang_config.get_system_prompt("")


def _persona_header(lang_config: LanguageConfig) -> str:
    """Short persona introduction used in each node's role_message.

    Includes an ABSOLUTE LANGUAGE LOCK: the model must respond only in
    the configured language, regardless of what the caller speaks, unless
    the caller explicitly asks to switch. This prevents drift when the
    caller code-mixes or when a task message contains examples.
    """
    return (
        f"You are {lang_config.persona_name}, a {lang_config.persona_gender} "
        f"AI voice assistant for IT-Webhut.\n\n"
        f"*** ABSOLUTE LANGUAGE RULE ***\n"
        f"Speak ONLY in {lang_config.name}. Even if the caller speaks a "
        f"different language or mixes languages, reply in {lang_config.name}. "
        f"Do NOT drift into Hindi, English, or any other language unless the "
        f"caller explicitly asks you to switch. This rule overrides every "
        f"instruction below.\n\n"
        f"Your responses will be converted to audio — keep them to 1-3 "
        f"natural spoken sentences. No markdown, no bullet points."
    )


# ====== HANDLER — record_interest ======
@idempotent_tool(ttl_seconds=60)
async def record_interest(
    flow_manager: FlowManager,
    interest: str,
) -> tuple[dict[str, Any], NodeConfig]:
    """Record what the caller is interested in and continue qualification."""
    redis = flow_manager.state.get("redis")
    call_id = flow_manager.state.get("call_id", "unknown")

    if redis and call_id != "unknown":
        await redis.update(call_id, interest=interest)

    flow_manager.state["interest"] = interest  # in-memory cache
    logger.info(f"[flows] record_interest: {interest!r}")
    return (
        {"status": "recorded", "interest": interest},
        _build_qualify_node(flow_manager),
    )


# ====== HANDLER — record_refusal ======
async def record_refusal(
    flow_manager: FlowManager,
    reason: str = "not_interested",
) -> tuple[dict[str, Any], NodeConfig]:
    """Record a refusal. Two refusals in a row transition to `confirm`."""
    redis = flow_manager.state.get("redis")
    call_id = flow_manager.state.get("call_id", "unknown")
    refusals = flow_manager.state.get("refusal_count", 0) + 1
    flow_manager.state["refusal_count"] = refusals
    flow_manager.state["last_refusal_reason"] = reason

    if redis and call_id != "unknown":
        await redis.update(
            call_id,
            refusal_count=refusals,
            last_refusal_reason=reason,
        )
    logger.info(f"[flows] record_refusal #{refusals}: {reason!r}")

    if refusals >= 2:
        logger.info("[flows] two refusals — transitioning to confirm")
        return (
            {"status": "confirm_needed", "refusals": refusals},
            _build_confirm_node(flow_manager),
        )

    return (
        {"status": "noted", "refusals": refusals},
        _build_qualify_node(flow_manager),
    )


@idempotent_tool(ttl_seconds=300)
async def record_consent(
    flow_manager: FlowManager,
    accepted: bool,
) -> tuple[dict[str, Any], NodeConfig | None]:
    """Record the caller's response to the AI-and-recording disclosure.

    Args:
        accepted: True if the caller agreed to proceed, False if they
            declined. Required.

    Returns:
        On acceptance, transitions to the qualify node. On decline,
        transitions to the closing node with the consent_decline_ack.
    """
    from datetime import UTC, datetime

    call_id = flow_manager.state.get("call_id", "unknown")
    audit = flow_manager.state.get("audit")
    supabase_store = flow_manager.state.get("supabase")

    if accepted:
        if audit is not None:
            await audit.record(call_id, "consent_captured", {"version": "v1"})
        if supabase_store is not None:
            try:
                await supabase_store.update_call(
                    call_id,
                    consent_captured_at=datetime.now(UTC).isoformat(),
                    disclosure_version="v1",
                )
            except Exception as e:
                logger.error(f"Failed to persist consent timestamp: {e}")
        logger.info(f"[flows] consent captured for {call_id}")
        return (
            {"status": "consent_granted"},
            _build_qualify_node(flow_manager),
        )

    if audit is not None:
        await audit.record(call_id, "consent_declined", {"version": "v1"})
    logger.info(f"[flows] consent declined for {call_id}")
    flow_manager.state["close_reason"] = "consent_declined"
    return (
        {"status": "consent_declined"},
        _build_closing_node(flow_manager),
    )


# ====== HANDLER — handle_wrong_number ======
async def handle_wrong_number(
    flow_manager: FlowManager,
) -> tuple[dict[str, Any], NodeConfig]:
    """Caller stated this is the wrong number — skip to closing."""
    session_state = _get_session_state(flow_manager)
    last_user = session_state.last_user_utterance if session_state else ""

    if not is_wrong_number(last_user):
        logger.warning("[flows] handle_wrong_number called but no match in state")
        return (
            {"status": "blocked", "reason": "no_explicit_wrong_number"},
            _build_qualify_node(flow_manager),
        )

    flow_manager.state["close_reason"] = "wrong_number"
    redis = flow_manager.state.get("redis")
    call_id = flow_manager.state.get("call_id", "unknown")
    if redis and call_id != "unknown":
        await redis.update(call_id, close_reason="wrong_number")
    logger.info("[flows] wrong number confirmed: transitioning to closing")
    return (
        {"status": "wrong_number_confirmed"},
        _build_closing_node(flow_manager),
    )


# ====== HANDLER — hang_up_call ======
@idempotent_tool(ttl_seconds=300)
async def hang_up_call(
    flow_manager: FlowManager,
    reason: str = "user_requested",
) -> tuple[dict[str, Any], NodeConfig | None]:
    """End the phone call. Only registered in `confirm` and `closing` nodes."""
    session_state = _get_session_state(flow_manager)
    redis = flow_manager.state.get("redis")
    call_id = flow_manager.state.get("call_id", "unknown")

    if session_state is None:
        logger.error("[flows] session_state missing from flow_manager.state")
        return (
            {"status": "error", "reason": "missing_state"},
            None,
        )

    last_user = session_state.last_user_utterance
    last_assistant = session_state.last_assistant_utterance
    confirmation_pending = session_state.confirmation_pending

    logger.info(
        f"[flows] hang_up_call invoked: reason={reason!r}, "
        f"last_user={last_user!r}, last_assistant={last_assistant!r}, "
        f"confirmation_pending={confirmation_pending}"
    )

    # ---- GUARD ----
    if reason == "wrong_number":
        allowed = is_wrong_number(last_user)
    elif confirmation_pending:
        # The assistant has already asked "do you want me to end the call?"
        # Any of these count as a yes: a literal affirmative, a busy/refusal
        # phrase ( the caller is  explaining why they want to end), or an
        # explicit goodbye.
        allowed = (
            is_affirmative_reply(last_user)
            or is_busy_response(last_user)
            or is_explicit_goodbye(last_user, last_assistant)
        )
    else:
        allowed = is_explicit_goodbye(last_user, last_assistant)

    if not allowed:
        logger.warning("[flows] hang_up_call BLOCKED: arming confirmation_pending")
        session_state.confirmation_pending = True
        if redis and call_id != "unknown":
            await redis.update(call_id, confirmation_pending=True)

        return (
            {
                "status": "blocked",
                "reason": "no_explicit_goodbye",
                "instruction": (
                    "The caller did NOT explicitly end the call. Ask them "
                    "directly, in the language they are using, whether they "
                    "want you to end the call now, and WAIT for their reply."
                ),
            },
            None,
        )

    # ---- PASSED ----
    logger.info("[flows] hang_up_call CONFIRMED — transitioning to closing")
    session_state.confirmation_pending = False
    flow_manager.state["close_reason"] = reason
    if redis and call_id != "unknown":
        await redis.update(
            call_id,
            confirmation_pending=False,
            close_reason=reason,
        )
    return (
        {"status": "confirmed", "reason": reason},
        _build_closing_node(flow_manager),
    )


# ====== NODE BUILDERS ======
def _build_greeting_node(lang_config: LanguageConfig) -> NodeConfig:
    """Opening node: speak the greeting and wait for the caller."""
    return NodeConfig(
        name="greeting",
        role_message=_persona_header(lang_config),
        task_messages=[
            {
                "role": "developer",
                "content": (
                    f"Say exactly this greeting, then stop and wait for the "
                    f"caller to respond: {lang_config.get_greeting()}"
                ),
            },
        ],
        functions=[],
        respond_immediately=True,
        post_actions=[
            {
                "type": "function",
                "handler": _transition_to_consent,
            }
        ],
    )


async def _transition_to_consent(
    action: dict[str, Any], flow_manager: FlowManager
) -> None:
    """Post-action on greeting: move to consent after greeting plays."""
    lang_config: LanguageConfig = flow_manager.state["lang_config"]
    await flow_manager.set_node_from_config(_build_consent_node(lang_config))


def _build_qualify_node(
    flow_manager_or_config: FlowManager | LanguageConfig,
) -> NodeConfig:
    """Qualification node — discuss objective, handle refusals."""
    if isinstance(flow_manager_or_config, FlowManager):
        lang_config: LanguageConfig = flow_manager_or_config.state["lang_config"]
    else:
        lang_config = flow_manager_or_config

    return NodeConfig(
        name="qualify",
        role_message=_persona_header(lang_config) + "\n\n" + _lang_block(lang_config),
        task_messages=[
            {
                "role": "developer",
                "content": (
                    "Discuss the caller's needs related to IT-Webhut's "
                    "services. Keep the conversation moving with short "
                    "questions. If the caller refuses or says they are "
                    "busy (e.g. 'नहीं धन्यवाद', 'not interested', "
                    "'I'm busy', 'व्यस्त हूँ', 'अभी बिज़ी हूँ', "
                    "'बाद में कॉल करें', 'call me later'), call "
                    "record_refusal with a short reason. Call the tool "
                    "on EVERY refusal — the system counts them and "
                    "decides when to transition. If the caller explicitly "
                    "says goodbye or asks to end the call, call "
                    "hang_up_call with reason='user_requested'. If the "
                    "caller says this is the wrong number, call "
                    "handle_wrong_number. If the caller states what they "
                    "are interested in, call record_interest with a "
                    "short summary."
                ),
            },
        ],
        functions=[record_interest, record_refusal, handle_wrong_number, hang_up_call],
        respond_immediately=False,
    )


def _build_consent_node(lang_config: LanguageConfig) -> NodeConfig:
    """Consent node: play DPDP disclosure and wait for caller reply."""
    return NodeConfig(
        name="consent",
        role_message=_persona_header(lang_config),
        task_messages=[
            {
                "role": "developer",
                "content": (
                    f"Say exactly this disclosure, then stop and wait for "
                    f"the caller's reply: {lang_config.consent_disclosure}\n\n"
                    f"If the caller says yes, हाँ, or ஆம் in any form, call "
                    f"record_consent with accepted=True. If the caller says "
                    f"no, नहीं, or இல்லை in any form, call record_consent "
                    f"with accepted=False. Do not proceed until you have a "
                    f"clear yes or no."
                ),
            },
        ],
        functions=[record_consent],
        respond_immediately=True,
    )


def _build_confirm_node(
    flow_manager_or_config: FlowManager | LanguageConfig,
) -> NodeConfig:
    """Confirm node — ask the caller if they want to end."""
    if isinstance(flow_manager_or_config, FlowManager):
        lang_config: LanguageConfig = flow_manager_or_config.state["lang_config"]
    else:
        lang_config = flow_manager_or_config

    return NodeConfig(
        name="confirm",
        role_message=_persona_header(lang_config),
        task_messages=[
            {
                "role": "developer",
                "content": (
                    "The caller has declined twice or seems to want to end "
                    "the call. Ask them directly, in the language they have "
                    "been using, whether they want you to end the call now. "
                    "Wait for their reply. If they say yes in any form, "
                    "call hang_up_call with reason='user_requested'. "
                    "If they say no, do NOT call any tool; continue the "
                    "conversation naturally."
                ),
            },
        ],
        functions=[hang_up_call],
        respond_immediately=True,
    )


def _build_closing_node(
    flow_manager_or_config: FlowManager | LanguageConfig,
) -> NodeConfig:
    """Closing node — speak farewell and end the call."""
    if isinstance(flow_manager_or_config, FlowManager):
        lang_config = flow_manager_or_config.state["lang_config"]
        close_reason = flow_manager_or_config.state.get(
            "close_reason", "user_requested"
        )
    else:
        lang_config = flow_manager_or_config
        close_reason = "user_requested"

    if close_reason == "wrong_number":
        farewell = lang_config.farewell_wrong_number
    elif close_reason == "consent_declined":
        farewell = lang_config.consent_decline_ack
    else:
        farewell = lang_config.farewell

    return NodeConfig(
        name="closing",
        role_message=_persona_header(lang_config),
        task_messages=[
            {
                "role": "developer",
                "content": (
                    f"Say exactly this farewell, then end the call: {farewell}"
                ),
            },
        ],
        functions=[hang_up_call],  # keep tool list non-empty for Sarvam API
        respond_immediately=True,
        post_actions=[{"type": "end_conversation"}],
    )


# ====== PUBLIC ENTRY POINT ======
def build_initial_node(lang_config: LanguageConfig) -> NodeConfig:
    """Return the first node the FlowManager should initialize with."""
    return _build_greeting_node(lang_config)
