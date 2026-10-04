import { callsSearchParamsCache } from "@/lib/search-params";

/**
 * Call list page. This placeholder exists so the sidebar's
 * "Calls" link does not 404 while Part 2 is being built.
 *
 * The current version reads the URL params and displays them as
 * plain text, which proves the nuqs plumbing works end to end:
 * the URL is parsed, defaults are applied, and a Server Component
 * receives the typed values without any client-side state.
 *
 * Part 2 replaces this body with the paginated table.
 */
export default async function CallsPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await callsSearchParamsCache.parse(searchParams);

  return (
    <div className="space-y-8">
      <div>
        <h2 className="text-2xl font-semibold tracking-tight">Calls</h2>
        <p className="text-sm text-muted-foreground">
          Every call the agent has made or received.
        </p>
      </div>

      <div className="rounded-lg border bg-card p-6">
        <p className="text-sm text-muted-foreground">
          URL state plumbing is in place. Parsed params:
        </p>
        <pre className="mt-3 rounded bg-muted p-3 text-xs">
          {JSON.stringify(params, null, 2)}
        </pre>
        <p className="mt-3 text-xs text-muted-foreground">
          Try appending <code>?page=2&amp;direction=outbound</code> to
          the URL and watching the parsed values change.
        </p>
      </div>
    </div>
  );
}
