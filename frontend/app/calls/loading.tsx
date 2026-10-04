import { Skeleton } from "@/components/ui/skeleton";

/**
 * Loading skeleton shown while the Server Component fetches.
 * Next.js renders this automatically whenever the calls route is
 * streaming in. It mirrors the shape of the table so the layout
 * does not jump when real data arrives.
 */
export default function Loading() {
  return (
    <div className="space-y-8">
      <div>
        <Skeleton className="h-8 w-32" />
        <Skeleton className="mt-2 h-4 w-64" />
      </div>

      <div className="rounded-lg border bg-card">
        <div className="border-b p-4">
          <Skeleton className="h-9 w-full max-w-md" />
        </div>
        <div className="p-4 space-y-3">
          {Array.from({ length: 8 }).map((_, i) => (
            <Skeleton key={i} className="h-10 w-full" />
          ))}
        </div>
      </div>
    </div>
  );
}
