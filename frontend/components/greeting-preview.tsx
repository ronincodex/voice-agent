"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

/**
 * Live preview of the greeting template with {name} and {company}
 * substituted.
 *
 * Subscribes to three fields via useWatch in the parent form.
 * Updates on every keystroke — the exact moment the operator sees
 * how their change will sound to the caller.
 *
 * This mirrors the substitution logic in the backend
 * (agent_pipeline.py::_apply_config_overrides). If a placeholder
 * has no value, we substitute a visible fallback rather than
 * leaving the literal `{name}` in the preview.
 */
export function GreetingPreview({
  template,
  agentName,
  companyName,
}: {
  template: string;
  agentName: string;
  companyName: string;
}) {
  const substituted = (template ?? "")
    .replace(/\{name\}/g, agentName?.trim() || "<agent name>")
    .replace(/\{company\}/g, companyName?.trim() || "<company>");

  const hasPlaceholders =
    (template ?? "").includes("{name}") ||
    (template ?? "").includes("{company}");

  return (
    <Card className="border-primary/40 bg-primary/5">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">
          Caller will hear
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        <p className="text-base leading-relaxed">
          &ldquo;{substituted}&rdquo;
        </p>
        <p className="text-xs text-muted-foreground">
          {hasPlaceholders
            ? "Placeholders were substituted with the values above."
            : "No {name} or {company} placeholders found in this greeting."}
        </p>
      </CardContent>
    </Card>
  );
}
