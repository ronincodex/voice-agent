import { Skeleton } from "@/components/ui/skeleton";

/**
 * Skeleton shown while the detail page fetches. Mirrors the
 * three-region layout (metadata, audio, transcript) so the page
 * does not jump when data arrives.
 */
export default function Loading() {
  return (
    <div className="space-y-6">
      <div>
        <Skeleton className="h-8 w-48" />
        <Skeleton className="mt-2 h-4 w-72" />
      </div>
      <div className="grid gap-4 md:grid-cols-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-32 w-full" />
        ))}
      </div>
      <Skeleton className="h-20 w-full" />
      <div className="space-y-3 rounded-lg border bg-card p-6">
        {Array.from({ length: 6 }).map((_, i) => (
          <Skeleton key={i} className="h-14 w-full" />
        ))}
      </div>
    </div>
  );
}
