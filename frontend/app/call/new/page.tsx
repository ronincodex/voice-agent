import { CallTriggerForm } from "@/components/call-trigger-form";
import { fetchApi } from "@/lib/api";

/**
 * New call page. Server Component fetches the supported languages
 * from the backend and hands them to the form. The form itself is
 * a Client Component because it manages input state.
 */

interface LanguageEntry {
  code: string;
  name: string;
}

interface LanguagesResponse {
  supported: LanguageEntry[];
  default: string;
}

export default async function NewCallPage() {
  const languages = await fetchApi<LanguagesResponse>("/languages");

  return (
    <div className="space-y-6 max-w-xl">
      <div>
        <h2 className="text-2xl font-semibold tracking-tight">New Call</h2>
        <p className="text-sm text-muted-foreground">
          Trigger an outbound call from the agent. The call connects to
          the number below within a few seconds.
        </p>
      </div>

      <CallTriggerForm
        languages={languages.supported}
        defaultLanguage={languages.default}
      />
    </div>
  );
}
