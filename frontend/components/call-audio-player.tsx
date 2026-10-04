"use client";

import { useEffect, useRef, useState } from "react";
import { Pause, Play, Volume2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Slider } from "@/components/ui/slider";
import { fetchApi } from "@/lib/api";
import type { RecordingUrl } from "@/lib/types";

/**
 * Audio playback for a single call recording.
 *
 * The presigned R2 URL is fetched lazily on the first play click.
 * Presigned URLs expire after one hour; fetching eagerly on mount
 * would waste a request and risk serving an expired URL to a user
 * who opens the page and waits before pressing play. Fetching on
 * demand means the URL is always fresh.
 *
 * State kept in React, not the URL. Playback position is transient
 * UI state — nobody shares a link at "1m 23s into the recording".
 * That is the opposite of the filters-and-pagination case where
 * URL state is correct.
 */
export function CallAudioPlayer({ callUuid }: { callUuid: string }) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const [url, setUrl] = useState<string | null>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;

    const onTimeUpdate = () => setCurrentTime(audio.currentTime);
    const onLoaded = () => setDuration(audio.duration);
    const onEnded = () => setIsPlaying(false);
    const onPlay = () => setIsPlaying(true);
    const onPause = () => setIsPlaying(false);

    audio.addEventListener("timeupdate", onTimeUpdate);
    audio.addEventListener("loadedmetadata", onLoaded);
    audio.addEventListener("ended", onEnded);
    audio.addEventListener("play", onPlay);
    audio.addEventListener("pause", onPause);

    return () => {
      audio.removeEventListener("timeupdate", onTimeUpdate);
      audio.removeEventListener("loadedmetadata", onLoaded);
      audio.removeEventListener("ended", onEnded);
      audio.removeEventListener("play", onPlay);
      audio.removeEventListener("pause", onPause);
    };
  }, []);

  async function togglePlay() {
    const audio = audioRef.current;
    if (!audio) return;

    if (isPlaying) {
      audio.pause();
      return;
    }

    if (!url) {
      try {
        const data = await fetchApi<RecordingUrl>(
          `/calls/${callUuid}/recording-url`,
        );
        setUrl(data.url);
        audio.src = data.url;
        await audio.play();
      } catch {
        setError("Recording is not available for this call.");
      }
    } else {
      await audio.play();
    }
  }

  function formatTime(seconds: number): string {
    if (!Number.isFinite(seconds)) return "0:00";
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m}:${s.toString().padStart(2, "0")}`;
  }

  return (
    <div className="flex items-center gap-3 rounded-lg border bg-card p-4">
      <audio ref={audioRef} preload="none" />
      <Button
        variant="outline"
        size="icon"
        className="h-10 w-10 shrink-0"
        onClick={togglePlay}
        disabled={!!error}
      >
        {isPlaying ? (
          <Pause className="h-4 w-4" />
        ) : (
          <Play className="h-4 w-4" />
        )}
      </Button>

      <span className="w-12 text-right text-xs tabular-nums text-muted-foreground">
        {formatTime(currentTime)}
      </span>

        <Slider
        value={[currentTime]}
        max={duration || 100}
        step={0.1}
        className="flex-1"
        onValueChange={(value) => {
          // Base UI's Slider emits `number | readonly number[]`
          // depending on whether the slider has a single thumb or
          // a range. Our slider has one thumb, but the type is
          // still a union. Normalise here rather than casting, so
          // a future range slider would not silently break.
          const next = typeof value === "number" ? value : value[0];
          const audio = audioRef.current;
          if (audio) {
            audio.currentTime = next;
            setCurrentTime(next);
          }
        }}
      />

      <span className="w-12 text-xs tabular-nums text-muted-foreground">
        {formatTime(duration)}
      </span>

      <Volume2 className="h-4 w-4 text-muted-foreground" />

      {error && (
        <span className="ml-2 text-xs text-muted-foreground">{error}</span>
      )}
    </div>
  );
}
