"""Per-stage latency metrics collection via a Pipecat Observer.

Pipecat emits MetricsFrame objects into the pipeline when
enable_metrics=True. Observers see every frame without being inserted
into the pipeline. This module subscribes to MetricsFrame pushes and
aggregates readings by stage.

Reference:
    https://docs.pipecat.ai/pipecat/fundamentals/metrics
    https://docs.pipecat.ai/api-reference/server/utilities/observers
"""

from collections import defaultdict
from typing import Any

from loguru import logger
from pipecat.frames.frames import MetricsFrame
from pipecat.observers.base_observer import BaseObserver, FramePushed


class MetricsCollector:
    """Accumulate latency and usage readings for one call."""

    def __init__(self) -> None:
        self._readings: dict[str, list[float]] = defaultdict(list)
        self._totals: dict[str, float] = defaultdict(float)

    def observe(self, key: str, value: float) -> None:
        self._readings[key].append(float(value))

    def observe_total(self, key: str, value: float) -> None:
        self._totals[key] += float(value)

    def aggregate(self) -> dict[str, dict[str, float]]:
        """Produce a JSON-serializable summary of all readings."""
        summary: dict[str, dict[str, float]] = {}

        for key, values in self._readings.items():
            if not values:
                continue
            ordered = sorted(values)
            n = len(ordered)
            summary[key] = {
                "count": float(n),
                "avg": round(sum(ordered) / n, 2),
                "min": round(ordered[0], 2),
                "max": round(ordered[-1], 2),
                "p50": round(ordered[n // 2], 2),
                "p95": round(ordered[min(int(n * 0.95), n - 1)], 2),
            }

        for key, total in self._totals.items():
            summary[key] = {"total": round(total, 2)}

        return summary


def _stage_from_processor(processor: str) -> str:
    """Map a Pipecat processor name to a short stage label."""
    if "STT" in processor:
        return "stt"
    if "LLM" in processor:
        return "llm"
    if "TTS" in processor:
        return "tts"
    return "other"


class MetricsObserver(BaseObserver):
    """Observer that feeds every MetricsFrame into a MetricsCollector."""

    def __init__(self, collector: MetricsCollector) -> None:
        super().__init__()
        self._collector = collector

    async def on_push_frame(self, data: FramePushed) -> None:
        frame = data.frame
        if not isinstance(frame, MetricsFrame):
            return

        for item in frame.data:
            self._route(item)

    def _route(self, item: Any) -> None:
        processor = getattr(item, "processor", "unknown")
        class_name = type(item).__name__
        stage = _stage_from_processor(processor)
        value = getattr(item, "value", None)

        if class_name == "TTFBMetricsData" and value is not None:
            self._collector.observe(f"{stage}.ttfb_ms", float(value) * 1000)

        elif class_name == "TTFAMetricsData":
            # TTFA has its own field, not .value
            ttfa = getattr(item, "ttfa", None)
            leading = getattr(item, "leading_silence", None)
            if ttfa is not None:
                self._collector.observe(f"{stage}.ttfa_ms", float(ttfa) * 1000)
            if leading is not None:
                self._collector.observe(
                    f"{stage}.leading_silence_ms", float(leading) * 1000
                )

        elif class_name == "TTFATMetricsData" and value is not None:
            self._collector.observe(f"{stage}.ttfat_ms", float(value) * 1000)

        elif class_name == "ProcessingMetricsData" and value is not None:
            self._collector.observe(f"{stage}.processing_ms", float(value) * 1000)

        elif class_name == "TextAggregationMetricsData" and value is not None:
            self._collector.observe(f"{stage}.text_aggregation_ms", float(value) * 1000)

        elif class_name == "LLMUsageMetricsData":
            usage = getattr(item, "value", None)
            if usage is not None:
                prompt = getattr(usage, "prompt_tokens", None)
                completion = getattr(usage, "completion_tokens", None)
                if prompt is not None:
                    self._collector.observe_total("llm.prompt_tokens", float(prompt))
                if completion is not None:
                    self._collector.observe_total(
                        "llm.completion_tokens", float(completion)
                    )

        elif class_name == "STTUsageMetricsData":
            usage = getattr(item, "value", None)
            audio_seconds = getattr(usage, "audio_seconds", None) if usage else None
            if audio_seconds is not None:
                self._collector.observe_total("stt.audio_seconds", float(audio_seconds))

        elif class_name == "TTSUsageMetricsData" and value is not None:
            self._collector.observe_total("tts.characters", float(value))

        else:
            logger.debug(f"Unhandled metric type: {class_name} from {processor}")
