import { ArrowDownLeft, ArrowUpRight } from "lucide-react";

/**
 * Small inline indicator for call direction. Green arrow for
 * inbound (someone called us), blue arrow for outbound (we called
 * them). Uses lucide icons which are already a dependency.
 */
export function CallDirectionBadge({ direction }: { direction: string }) {
  const inbound = direction === "inbound";
  const Icon = inbound ? ArrowDownLeft : ArrowUpRight;

  return (
    <span className="inline-flex items-center gap-1 text-xs">
      <Icon
        className={
          inbound ? "h-3.5 w-3.5 text-emerald-600" : "h-3.5 w-3.5 text-blue-600"
        }
      />
      <span className="capitalize text-muted-foreground">{direction}</span>
    </span>
  );
}
