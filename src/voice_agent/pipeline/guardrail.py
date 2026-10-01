"""Real-time prompt injection detector.

Matches known injection patterns in TranscriptionFrames and deflects
without forwarding the frame to the LLM.

Design follows NVIDIA's voice-agent-examples GuardrailProcessor: check
the transcription, push a TTSSpeakFrame to deflect, return without
forwarding the original frame. TTSSpeakFrame bypasses the LLM, so the
injection never enters the model's context.

Constraint: Pipecat frame processing events are synchronous. No I/O,
no awaits beyond super().process_frame and push_frame. Audit events
are deferred to the post-call finally block.

Pattern source: OWASP LLM Prompt Injection Prevention Cheat Sheet,
via the production regex catalog published by OpenRouter.
"""

import re

from loguru import logger
from pipecat.frames.frames import Frame, TranscriptionFrame, TTSSpeakFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


class PromptInjectionGuard(FrameProcessor):
    """Block transcription frames matching known injection patterns."""

    _PATTERNS: list[re.Pattern[str]] = [
        # 1. Instruction override: ignore/disregard/forget + prior instructions
        re.compile(
            r"\b(ignore|disregard|forget)\b.{0,60}"
            r"\b(previous|prior|above|earlier|initial|original|system)\b.{0,20}"
            r"\b(instructions?|rules?|guidelines?|prompt|directives?)\b",
            re.IGNORECASE | re.DOTALL,
        ),
        # 2. New instructions marker
        re.compile(r"\bnew\s+instructions?\s*:", re.IGNORECASE),
        # 3. System prompt extraction
        re.compile(
            r"\b(system\s+prompt|your\s+instructions|your\s+system|"
            r"reveal\s+your|repeat\s+your\s+(instructions|prompt))\b",
            re.IGNORECASE,
        ),
        # 4. Role manipulation / developer mode
        re.compile(
            r"\b(you\s+are\s+now|act\s+as|pretend\s+to\s+be|"
            r"developer\s+mode|jailbreak|DAN\s+mode)\b",
            re.IGNORECASE,
        ),
        # 5. ChatML / OpenAI special-token injection
        re.compile(
            r"<\s*\|?\s*(im_start|im_end|endoftext|system|assistant)\s*\|?\s*>",
            re.IGNORECASE,
        ),
        # 6. Do not follow / supersede / void instructions.
        # Order-insensitive: matches keyword-then-target and
        # target-then-keyword. STT can produce either.
        re.compile(
            r"(?:"
            r"\b(?:do\s+not\s+follow|supersedes?|(?:are|is)\s+(?:now\s+)?void|"
            r"are\s+invalid|null\s+and\s+void)\b.{0,60}"
            r"\b(?:system|developer|previous|prior|original|instructions?)\b"
            r"|"
            r"\b(?:system|developer|previous|prior|original|instructions?)\b.{0,60}"
            r"\b(?:do\s+not\s+follow|supersedes?|(?:are|is)\s+(?:now\s+)?void|"
            r"are\s+invalid|null\s+and\s+void)\b"
            r")",
            re.IGNORECASE | re.DOTALL,
        ),
    ]

    def __init__(self, deflect_message: str) -> None:
        super().__init__()
        self._deflect = deflect_message
        self._flagged_count = 0

    @property
    def flagged_count(self) -> int:
        """Number of injection attempts blocked during this call."""
        return self._flagged_count

    async def process_frame(
        self,
        frame: Frame,
        direction: FrameDirection,
    ) -> None:
        await super().process_frame(frame, direction)

        if isinstance(frame, TranscriptionFrame):
            for pattern in self._PATTERNS:
                if pattern.search(frame.text):
                    self._flagged_count += 1
                    logger.warning(
                        f"guardrail_prompt_injection "
                        f"pattern={pattern.pattern[:40]!r} "
                        f"text={frame.text[:80]!r}"
                    )
                    # Deflect via TTS (bypasses the LLM entirely) and
                    # drop the original frame so it never enters the
                    # LLM context.
                    await self.push_frame(
                        TTSSpeakFrame(self._deflect),
                        FrameDirection.DOWNSTREAM,
                    )
                    return

        await self.push_frame(frame, direction)
