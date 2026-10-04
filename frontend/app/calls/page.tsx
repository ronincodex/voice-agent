import { CallsFilters } from "@/components/calls-filters";
import { CallsPagination } from "@/components/calls-pagination";
import { CallsTable } from "@/components/calls-table";
import { fetchPaginated } from "@/lib/api";
import { callsSearchParamsCache } from "@/lib/search-params";
import type { CallSummary } from "@/lib/types";

/**
 * Call list page. Server Component that reads the URL params,
 * forwards them as query string to the backend, and passes the
 * rows to the table.
 *
 * Data flow:
 *   1. URL contains page / direction / status / language
 *   2. callsSearchParamsCache parses and validates them
 *   3. We build a matching query string for the backend
 *   4. fetchPaginated<CallSummary> hits /calls with that query
 *   5. The envelope's data array goes to CallsTable
 *
 * The Server Component re-runs on every URL change because
 * searchParams is a dynamic value. No client-side re-fetch, no
 * useEffect, no loading spinners after the initial render —
 * loading.tsx covers the streaming case.
 */
const PAGE_SIZE = 20;

export default async function CallsPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await callsSearchParamsCache.parse(searchParams);

  // Build the query string for the backend. Only include params
  // that are set, so the URL stays clean and the backend receives
  // exactly what it needs.
  const query = new URLSearchParams();
  query.set("page", String(params.page));
  query.set("limit", String(PAGE_SIZE));
  if (params.direction) query.set("direction", params.direction);
  if (params.status) query.set("status", params.status);
  if (params.language) query.set("language", params.language);

  const result = await fetchPaginated<CallSummary>(`/calls?${query.toString()}`);

  return (
    <div className="space-y-8">
      <div className="flex items-end justify-between">
        <div>
          <h2 className="text-2xl font-semibold tracking-tight">Calls</h2>
          <p className="text-sm text-muted-foreground">
            {result.total} {result.total === 1 ? "call" : "calls"} total
          </p>
        </div>
      </div>

      {/* Filters and pagination controls arrive in Part 3.*/}

            <CallsFilters />

      <CallsTable data={result.data} />

      <CallsPagination
        total={result.total}
        page={result.page}
        limit={result.limit}
      />    </div>
  );
}
