import { ArrowDownLeft, ArrowUpRight, Clock, Globe } from "lucide-react";

import { CallStatusBadge } from "@/components/call-status-badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { CallDetail } from "@/lib/types";

/**
 * Header block for a call: four cards showing direction, numbers,
 * duration, and AI summary. Server Component — no hooks, no state.
 *
 * The summary is rendered from the JSONB blob the summariser wrote
 * to calls.summary. It has a known shape (outcome, summary,
 * next_action) but is typed as `dict | null` on the backend, so we
 * guard against a missing or malformed value and show a placeholder
 * instead of crashing the detail page.
 */
function formatDuration(seconds: number | null): string {
  if (seconds === null) return "—";
  if (seconds < 60) return `${seconds}s`;
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}m ${s}s`;
}

function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString("en-IN", {
    dateStyle: "medium",
    timeStyle: "short",
    hour12: false,
  });
}

export function CallMetadata({ call }: { call: CallDetail }) {
  const inbound = call.direction === "inbound";
  const DirectionIcon = inbound ? ArrowDownLeft : ArrowUpRight;
  const directionLabel = inbound ? "Inbound" : "Outbound";
  const directionColor = inbound
    ? "text-emerald-600"
    : "text-blue-600";

  return (
    <div className="space-y-4">
      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Direction
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex items-center gap-2">
              <DirectionIcon className={`h-5 w-5 ${directionColor}`} />
              <span className="text-lg font-semibold">{directionLabel}</span>
            </div>
            <p className="mt-1 text-xs text-muted-foreground">
              {formatDateTime(call.started_at)}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              From → To
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="font-mono text-sm">
              {call.from_number || "—"}
            </p>
            <p className="mt-1 font-mono text-sm text-muted-foreground">
              {call.to_number || "—"}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Duration
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex items-center gap-2">
              <Clock className="h-5 w-5 text-muted-foreground" />
              <span className="text-lg font-semibold tabular-nums">
                {formatDuration(call.duration_seconds)}
              </span>
            </div>
            <div className="mt-1 flex items-center gap-2">
              <Globe className="h-3.5 w-3.5 text-muted-foreground" />
              <span className="text-xs text-muted-foreground">
                {call.language}
              </span>
              <CallStatusBadge status={call.status} />
            </div>
          </CardContent>
        </Card>
      </div>

      {call.summary && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              AI Summary — {call.summary.outcome}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            <p className="text-sm leading-relaxed">{call.summary.summary}</p>
            <p className="text-xs text-muted-foreground">
              <span className="font-medium">Next action:</span>{" "}
              {call.summary.next_action}
            </p>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
