"use client";

import { X } from "lucide-react";
import { useQueryStates } from "nuqs";

import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  callsSearchParams,
  DIRECTION_VALUES,
  STATUS_VALUES,
  type DirectionFilter,
  type StatusFilter,
} from "@/lib/search-params";

/**
 * Filter bar for the calls table.
 *
 * Every change writes to the URL through nuqs. That triggers the
 * Server Component to re-render with the new searchParams, which
 * re-runs the query. There is no React state, no useEffect, no
 * client-side filtering — the URL is the single source of truth.
 *
 * The "all" sentinel exists because the shadcn Select component
 * requires a non-empty string for its value prop. We translate it
 * to null when writing, and back to "all" when reading, so the
 * URL stays clean: /calls?direction=outbound, not
 * /calls?direction=all.
 *
 * Page resets to 1 on every filter change. Without this, a user
 * on page 5 who narrows the filter to a category with 10 results
 * would land on an empty page 5.
 */
export function CallsFilters() {
  // shallow: false is set on each parser in lib/search-params.ts,
  // so every change from this hook triggers a Server Component
  // re-render. No option needed here.
  const [params, setParams] = useQueryStates(callsSearchParams);
  
  const hasFilters = Boolean(params.direction || params.status);

  const directionValue = params.direction ?? "all";
  const statusValue = params.status ?? "all";

  return (
    <div className="flex flex-wrap items-center gap-2">
      <Select
        value={directionValue}
        onValueChange={(value) =>
          setParams({
            direction: value === "all" ? null : (value as DirectionFilter),
            page: 1,
          })
        }
      >
        <SelectTrigger className="w-[160px]">
          <SelectValue placeholder="Direction" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">All directions</SelectItem>
          {DIRECTION_VALUES.map((d) => (
            <SelectItem key={d} value={d}>
              {d.charAt(0).toUpperCase() + d.slice(1)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      <Select
        value={statusValue}
        onValueChange={(value) =>
          setParams({
            status: value === "all" ? null : (value as StatusFilter),
            page: 1,
          })
        }
      >
        <SelectTrigger className="w-[180px]">
          <SelectValue placeholder="Status" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">All statuses</SelectItem>
          {STATUS_VALUES.map((s) => (
            <SelectItem key={s} value={s}>
              {s
                .split("-")
                .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
                .join(" ")}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      {hasFilters && (
        <Button
          variant="ghost"
          size="sm"
          onClick={() => setParams({ direction: null, status: null, page: 1 })}
        >
          <X className="mr-1 h-3.5 w-3.5" />
          Clear
        </Button>
      )}
    </div>
  );
}
