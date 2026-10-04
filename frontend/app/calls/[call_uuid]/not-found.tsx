import Link from "next/link";
import { PhoneOff } from "lucide-react";

import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/**
 * Route-specific 404 for /calls/[call_uuid].
 *
 * Uses buttonVariants on a plain <Link> rather than wrapping Link
 * inside <Button>. Base UI's Button always applies role="button",
 * which overrides the anchor's semantic link role — bad for
 * accessibility and for browser link affordances like middle-click
 * and "open in new tab". The buttonVariants helper produces the
 * same visual style without that side effect.
 */
export default function CallNotFound() {
  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center gap-4 text-center">
      <div className="rounded-full bg-muted p-4">
        <PhoneOff className="h-8 w-8 text-muted-foreground" />
      </div>
      <div>
        <h2 className="text-lg font-semibold">Call not found</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          This call either never existed or is no longer available.
        </p>
      </div>
      <Link
        href="/calls"
        className={cn(buttonVariants({ variant: "outline" }))}
      >
        Back to calls
      </Link>
    </div>
  );
}
