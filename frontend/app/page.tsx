import { Activity, Phone, PhoneCall, PhoneOff } from "lucide-react";

import { StatCard } from "@/components/stat-card";
import { fetchApi } from "@/lib/api";
import type { CallStats } from "@/lib/types";

/**
 * Dashboard home. Fetches the four counter values from the backend
 * at request time and renders them in a 4-column grid.
 *
 * This is a Server Component: `async function` component, no
 * "use client" directive. The fetch runs on the Next.js server,
 * not in the browser, so it is not subject to CORS. The CORS
 * middleware we added to the backend is for the Client Components
 * that later phases will introduce.
 */
export default async function Home() {
  const stats = await fetchApi<CallStats>("/calls/stats");

  return (
    <div className="space-y-8">
      <div>
        <h2 className="text-2xl font-semibold tracking-tight">Dashboard</h2>
        <p className="text-sm text-muted-foreground">
          Overview of every call the agent has made or received.
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <StatCard
          title="Total Calls"
          value={stats.total}
          icon={Phone}
          description="All-time"
        />
        <StatCard
          title="Completed"
          value={stats.completed}
          icon={PhoneCall}
          description="Reached the end"
        />
        <StatCard
          title="Failed"
          value={stats.failed}
          icon={PhoneOff}
          description="No answer, busy, or error"
        />
        <StatCard
          title="In Progress"
          value={stats.in_progress}
          icon={Activity}
          description="Initiated, ringing, active"
        />
      </div>
    </div>
  );
}
