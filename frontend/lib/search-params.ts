import {
  parseAsInteger,
  parseAsString,
  parseAsStringLiteral,
  createSearchParamsCache,
} from "nuqs/server";

/**
 * URL parameter schema for the calls list page.
 *
 * Why these live in one file:
 *   The Server Component reads the params to build the query, and
 *   the Client Component writes them when the user clicks a filter
 *   or a page button. If the schema were duplicated in both
 *   places, a rename in one would silently break the other. Here
 *   there is exactly one definition, imported by both.
 *
 * URL shape:
 *   /calls?page=2&direction=outbound&status=completed
 *
 * Defaults:
 *   - page: 1 (first page)
 *   - direction: null (all directions)
 *   - status: null (all statuses)
 *
 * Null values are omitted from the URL by nuqs' default
 * behaviour, so /calls renders the full list with no visible
 * query string. That keeps the clean URL for the common case.
 */

export const DIRECTION_VALUES = ["inbound", "outbound"] as const;
export const STATUS_VALUES = [
  "initiated",
  "ringing",
  "in-progress",
  "completed",
  "no-answer",
  "busy",
  "failed",
  "timeout",
  "cancel",
] as const;

export type DirectionFilter = (typeof DIRECTION_VALUES)[number];
export type StatusFilter = (typeof STATUS_VALUES)[number];

/**
 * Every parser carries shallow: false so a URL change triggers a
 * Next.js navigation and re-runs the Server Component. The default
 * in nuqs 2.x is shallow: true, which updates the URL via
 * history.replaceState without a navigation — correct for
 * client-only filter state, wrong for our architecture where the
 * URL drives a server fetch.
 *
 * Defining it here means every consumer of callsSearchParams
 * inherits the option. If it lived in the components, one missing
 * shallow: false in a future file would silently break server
 * refetching for that control only, which is a hard bug to spot.
 */
const serverSyncOptions = { shallow: false } as const;

export const callsSearchParams = {
  page: parseAsInteger.withDefault(1).withOptions(serverSyncOptions),
  direction: parseAsStringLiteral(DIRECTION_VALUES).withOptions(
    serverSyncOptions,
  ),
  status: parseAsStringLiteral(STATUS_VALUES).withOptions(serverSyncOptions),
  language: parseAsString.withOptions(serverSyncOptions),
};

/**
 * Server-side cache. A Server Component calls
 * `callsSearchParamsCache.parse(searchParams)` to get the parsed
 * values in a single synchronous read. The result is memoized per
 * request, so multiple consumers within the same render see the
 * same parsed object.
 */
export const callsSearchParamsCache = createSearchParamsCache(callsSearchParams);
