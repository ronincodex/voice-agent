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
from voice_agent.pipeline.validators import (
    is_affirmative_reply,
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
    """Short persona introduction used in each node's role_message."""
    return (
        f"You are {lang_config.persona_name}, a {lang_config.persona_gender} "
        f"AI voice assistant for IT-Webhut. You speak {lang_config.name}. "
        f"Your responses will be converted to audio — keep them to 1-3 "
        f"natural spoken sentences. No markdown, no bullet points."
    )


# ====== HANDLER — record_interest ======
async def record_interest(
    flow_manager: FlowManager,
    interest: str,
) -> tuple[dict[str, Any], NodeConfig]:
    """Record what the caller is interested in and continue qualification."""
    flow_manager.state["interest"] = interest
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
    refusals = flow_manager.state.get("refusal_count", 0) + 1
    flow_manager.state["refusal_count"] = refusals
    flow_manager.state["last_refusal_reason"] = reason
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
    logger.info("[flows] wrong number confirmed: transitioning to closing")
    return (
        {"status": "wrong_number_confirmed"},
        _build_closing_node(flow_manager),
    )


# ====== HANDLER — hang_up_call ======
async def hang_up_call(
    flow_manager: FlowManager,
    reason: str = "user_requested",
) -> tuple[dict[str, Any], NodeConfig | None]:
    """End the phone call. Only registered in `confirm` and `closing` nodes."""
    session_state = _get_session_state(flow_manager)

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
    else:
        allowed = is_explicit_goodbye(last_user, last_assistant) or (
            confirmation_pending and is_affirmative_reply(last_user)
        )

    if not allowed:
        logger.warning("[flows] hang_up_call BLOCKED — arming confirmation_pending")
        session_state.confirmation_pending = True
        return (
            {
                "status": "blocked",
                "reason": "no_explicit_goodbye",
                "instruction": (
                    "The caller did NOT explicitly end the call. Ask them "
                    "directly: 'क्या आप चाहते हैं कि मैं अभी call end कर दूँ?' "
                    "(or the caller's language equivalent) and WAIT for their reply."
                ),
            },
            None,
        )

    # ---- PASSED ----
    logger.info("[flows] hang_up_call CONFIRMED — transitioning to closing")
    session_state.confirmation_pending = False
    flow_manager.state["close_reason"] = reason
    return (
        {"status": "confirmed", "reason": reason},
        _build_closing_node(flow_manager),
    )


# ====== NODE BUILDERS ======
def _build_greeting_node(lang_config: LanguageConfig) -> NodeConfig:
    """Opening node — speak the greeting and wait for the caller."""
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
                "handler": _transition_to_qualify,
            }
        ],
    )


async def _transition_to_qualify(
    action: dict[str, Any], flow_manager: FlowManager
) -> None:
    """Post-action on greeting node — move to qualify after greeting plays."""
    lang_config: LanguageConfig = flow_manager.state["lang_config"]
    await flow_manager.set_node_from_config(_build_qualify_node(lang_config))


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
                    "questions. If the caller refuses twice in a row "
                    '("नहीं धन्यवाद", "not interested", "I\'m busy"), '
                    "call record_refusal. If the caller explicitly says "
                    "goodbye or asks to end the call, call hang_up_call "
                    "with reason='user_requested'. If the caller says this "
                    "is the wrong number, call handle_wrong_number. If the "
                    "caller states what they are interested in, call "
                    "record_interest with a short summary."
                ),
            },
        ],
        functions=[record_interest, record_refusal, handle_wrong_number, hang_up_call],
        respond_immediately=False,
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
                    "the call. Ask them directly, in their language: "
                    "'क्या आप चाहते हैं कि मैं अभी call end कर दूँ?' "
                    "(or 'Would you like me to end the call now?'). "
                    "Wait for their reply. If they say yes/हाँ/बिल्कुल, "
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
        lang_config: LanguageConfig = flow_manager_or_config.state["lang_config"]
        close_reason = flow_manager_or_config.state.get(
            "close_reason", "user_requested"
        )
    else:
        lang_config = flow_manager_or_config
        close_reason = "user_requested"

    farewell = (
        lang_config.farewell_wrong_number
        if close_reason == "wrong_number"
        else lang_config.farewell
    )

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
        functions=[],
        respond_immediately=True,
        post_actions=[{"type": "end_conversation"}],
    )


# ====== PUBLIC ENTRY POINT ======
def build_initial_node(lang_config: LanguageConfig) -> NodeConfig:
    """Return the first node the FlowManager should initialize with."""
    return _build_greeting_node(lang_config)
