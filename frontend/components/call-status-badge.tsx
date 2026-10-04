import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

/**
 * Map a call status to a badge variant and a human-readable label.
 *
 * The mapping lives in one place so a status added to the backend
 * schema (docs/schema.sql, calls.status CHECK constraint) is a
 * one-line change here. Unknown statuses fall through to a neutral
 * gray badge rather than crashing.
 */
const STATUS_VARIANTS = {
  completed: {
    label: "Completed",
    className: "bg-emerald-50 text-emerald-700 border-emerald-200",
  },
  "in-progress": {
    label: "In Progress",
    className: "bg-amber-50 text-amber-700 border-amber-200",
  },
  ringing: {
    label: "Ringing",
    className: "bg-amber-50 text-amber-700 border-amber-200",
  },
  initiated: {
    label: "Initiated",
    className: "bg-slate-50 text-slate-700 border-slate-200",
  },
  failed: {
    label: "Failed",
    className: "bg-red-50 text-red-700 border-red-200",
  },
  "no-answer": {
    label: "No Answer",
    className: "bg-red-50 text-red-700 border-red-200",
  },
  busy: {
    label: "Busy",
    className: "bg-red-50 text-red-700 border-red-200",
  },
  timeout: {
    label: "Timeout",
    className: "bg-red-50 text-red-700 border-red-200",
  },
  cancel: {
    label: "Cancelled",
    className: "bg-red-50 text-red-700 border-red-200",
  },
} as const;

export function CallStatusBadge({ status }: { status: string }) {
  const variant =
    STATUS_VARIANTS[status as keyof typeof STATUS_VARIANTS] ?? {
      label: status,
      className: "bg-slate-50 text-slate-700 border-slate-200",
    };

  return (
    <Badge
      variant="outline"
      className={cn("font-normal", variant.className)}
    >
      {variant.label}
    </Badge>
  );
}
