import { AgentConfigForm } from "@/components/agent-config-form";
import { fetchApi } from "@/lib/api";
import type { AgentConfig } from "@/lib/types";

/**
 * Agent configuration page. Server Component reads the current
 * config from GET /agents/config and hands it to the form as
 * initial values.
 *
 * After a save, the form calls router.refresh(), which re-runs
 * this Server Component and re-fetches. The form gets fresh
 * initial values without losing its RHF state.
 */
export default async function ConfigPage() {
  const config = await fetchApi<AgentConfig>("/agents/config");

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-semibold tracking-tight">
          Agent Configuration
        </h2>
        <p className="text-sm text-muted-foreground">
          Changes take effect on the next call. The greeting preview
          updates as you type.
        </p>
      </div>

      <AgentConfigForm initialConfig={config} />
    </div>
  );
}
