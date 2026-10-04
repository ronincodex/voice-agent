"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";
import { useQueryState } from "nuqs";

import { Button } from "@/components/ui/button";
import { callsSearchParams } from "@/lib/search-params";

interface CallsPaginationProps {
  total: number;
  page: number;
  limit: number;
}

/**
 * Pagination controls for the calls table.
 *
 * shallow: false is critical. It tells nuqs to route the URL change
 * through the Next.js App Router instead of updating the history
 * directly. Without it, the URL bar changes but the Server
 * Component never re-runs, so the table shows stale rows. The
 * default in nuqs 2.x is shallow: true, which is correct for
 * client-only state but wrong for our architecture where the URL
 * drives a Server Component fetch.
 */
export function CallsPagination({ total, page, limit }: CallsPaginationProps) {
  const [, setPage] = useQueryState("page", callsSearchParams.page);
  const totalPages = Math.max(1, Math.ceil(total / limit));
  const start = total === 0 ? 0 : (page - 1) * limit + 1;
  const end = Math.min(page * limit, total);
  const canPrevious = page > 1;
  const canNext = page < totalPages;

  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
      <p className="text-sm text-muted-foreground">
        Showing <span className="font-medium tabular-nums">{start}</span>–
        <span className="font-medium tabular-nums">{end}</span> of{" "}
        <span className="font-medium tabular-nums">{total}</span>
      </p>
      <div className="flex items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          disabled={!canPrevious}
          onClick={() => setPage(page - 1)}
        >
          <ChevronLeft className="mr-1 h-3.5 w-3.5" />
          Previous
        </Button>
        <span className="px-2 text-sm tabular-nums text-muted-foreground">
          Page {page} of {totalPages}
        </span>
        <Button
          variant="outline"
          size="sm"
          disabled={!canNext}
          onClick={() => setPage(page + 1)}
        >
          Next
          <ChevronRight className="ml-1 h-3.5 w-3.5" />
        </Button>
      </div>
    </div>
  );
}
