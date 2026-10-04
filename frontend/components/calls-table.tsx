"use client";

import Link from "next/link";
import {
  columnFilteringFeature,
  columnVisibilityFeature,
  createColumnHelper,
  rowPaginationFeature,
  rowSortingFeature,
  tableFeatures,
  useTable,
} from "@tanstack/react-table";

import { CallDirectionBadge } from "@/components/call-direction-badge";
import { CallStatusBadge } from "@/components/call-status-badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { CallSummary } from "@/lib/types";

/**
 * Format a duration in seconds as "1m 23s" or "45s".
 */
function formatDuration(seconds: number | null): string {
  if (seconds === null) return "—";
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  return `${minutes}m ${remainder}s`;
}

/**
 * Format an ISO timestamp as a compact local string. Uses the
 * India locale for consistency with the backend's IST window.
 */
function formatTimestamp(iso: string): string {
  const date = new Date(iso);
  return date.toLocaleString("en-IN", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

/**
 * TanStack Table v9 feature declaration.
 *
 * v9 requires every capability to be registered before its options
 * and APIs exist on the type. Registering a feature gives us the
 * state, options, event handlers, and instance APIs. It does NOT
 * perform client-side processing — that is the job of a row model
 * factory, which we deliberately do not register.
 *
 * The four features below exist only so the following are valid:
 *
 *   columnFilteringFeature   -> manualFiltering option
 *   rowSortingFeature        -> manualSorting option
 *   rowPaginationFeature     -> manualPagination option
 *   columnVisibilityFeature  -> row.getVisibleCells() API
 *
 * Our backend already paginates, filters, and sorts. The table
 * renders exactly the 20 rows it receives. A future developer who
 * wants client-side sorting must additionally register
 * `sortedRowModel: createSortedRowModel()` here — without it, the
 * sorting APIs exist but do nothing.
 */
const features = tableFeatures({
  columnFilteringFeature,
  columnVisibilityFeature,
  rowPaginationFeature,
  rowSortingFeature,
});

const columnHelper = createColumnHelper<typeof features, CallSummary>();

/**
 * Column definitions. `manual*` flags on the table below tell
 * TanStack Table that the server already paginated, filtered, and
 * sorted. These columns are a rendering configuration only.
 */
const columns = columnHelper.columns([
  columnHelper.accessor("direction", {
    header: "Direction",
    cell: (info) => <CallDirectionBadge direction={info.getValue()} />,
  }),
  columnHelper.accessor("from_number", {
    header: "From",
    cell: (info) => (
      <span className="font-mono text-xs">{info.getValue() || "—"}</span>
    ),
  }),
  columnHelper.accessor("to_number", {
    header: "To",
    cell: (info) => (
      <span className="font-mono text-xs">{info.getValue() || "—"}</span>
    ),
  }),
  columnHelper.accessor("language", {
    header: "Language",
    cell: (info) => (
      <span className="text-xs text-muted-foreground">{info.getValue()}</span>
    ),
  }),
  columnHelper.accessor("status", {
    header: "Status",
    cell: (info) => <CallStatusBadge status={info.getValue()} />,
  }),
  columnHelper.accessor("duration_seconds", {
    header: "Duration",
    cell: (info) => (
      <span className="tabular-nums">{formatDuration(info.getValue())}</span>
    ),
  }),
  columnHelper.accessor("started_at", {
    header: "Started",
    cell: (info) => (
      <span className="tabular-nums text-muted-foreground">
        {formatTimestamp(info.getValue())}
      </span>
    ),
  }),
  columnHelper.display({
    id: "open",
    header: "",
    cell: ({ row }) => (
      <Link
        href={`/calls/${row.original.call_uuid}`}
        className="text-xs font-medium text-primary hover:underline"
      >
        Open
      </Link>
    ),
  }),
]);

export function CallsTable({ data }: { data: CallSummary[] }) {
  const table = useTable({
    features,
    data,
    columns,
    // The three manual* flags tell the table the server did the
    // work. Without them, the table would try to paginate the 20
    // rows it receives as if they were the entire dataset.
    manualPagination: true,
    manualFiltering: true,
    manualSorting: true,
  });

  return (
    <div className="rounded-lg border bg-card">
      <Table>
        <TableHeader>
          {table.getHeaderGroups().map((headerGroup) => (
            <TableRow key={headerGroup.id}>
              {headerGroup.headers.map((header) => (
                <TableHead key={header.id}>
                  {header.isPlaceholder ? null : (
                    <table.FlexRender header={header} />
                  )}
                </TableHead>
              ))}
            </TableRow>
          ))}
        </TableHeader>
        <TableBody>
          {table.getRowModel().rows.length === 0 ? (
            <TableRow>
              <TableCell
                colSpan={columns.length}
                className="h-24 text-center text-sm text-muted-foreground"
              >
                No calls match the current filters.
              </TableCell>
            </TableRow>
          ) : (
            table.getRowModel().rows.map((row) => (
              <TableRow key={row.id}>
                {row.getVisibleCells().map((cell) => (
                  <TableCell key={cell.id}>
                    <table.FlexRender cell={cell} />
                  </TableCell>
                ))}
              </TableRow>
            ))
          )}
        </TableBody>
      </Table>
    </div>
  );
}
