"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { Loader2, RotateCcw, Save } from "lucide-react";
import { toast } from "sonner";

import { GreetingPreview } from "@/components/greeting-preview";
import { Button } from "@/components/ui/button";
import {
  Field,
  FieldDescription,
  FieldError,
  FieldGroup,
  FieldLabel,
} from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import {
  AgentConfigSchema,
  LANGUAGE_CODES,
  type AgentConfigFormValues,
} from "@/lib/agent-config-schema";
import { ApiError } from "@/lib/api";
import type { AgentConfig } from "@/lib/types";

/**
 * Agent configuration form.
 *
 * RHF handles state and validation. On submit, we PUT to
 * /agents/config and use the response as the new source of truth.
 * On success, we call router.refresh() so the Server Component
 * re-fetches — the form stays mounted, only the initialConfig
 * prop changes.
 *
 * Reset discards unsaved edits and re-fetches from the server.
 * It does NOT reset to hardcoded defaults — a user who misclicks
 * would lose everything they typed.
 */
export function AgentConfigForm({
  initialConfig,
}: {
  initialConfig: AgentConfig;
}) {
  const router = useRouter();
  const [saving, setSaving] = useState(false);

  const form = useForm<AgentConfigFormValues>({
    resolver: zodResolver(AgentConfigSchema),
    defaultValues: {
      agent_name: initialConfig.agent_name,
      company_name: initialConfig.company_name,
      company_info: initialConfig.company_info,
      objective: initialConfig.objective,
      personality: initialConfig.personality,
      greeting_template: initialConfig.greeting_template,
      max_call_duration_seconds: initialConfig.max_call_duration_seconds,
      primary_language: initialConfig.primary_language,
      supported_languages: initialConfig.supported_languages,
      voice_overrides: initialConfig.voice_overrides,
    },
  });

const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isDirty },
  } = form;

  // useWatch subscribes to specific fields and returns their
  // current values. Preferred over watch() because watch() returns
  // a function React Compiler cannot memoize, which disables
  // memoization for the whole component and produces the
  // 'Compilation Skipped' lint warning.
  const watchedGreeting = useWatch({
    control: form.control,
    name: "greeting_template",
  });
  const watchedName = useWatch({
    control: form.control,
    name: "agent_name",
  });
  const watchedCompany = useWatch({
    control: form.control,
    name: "company_name",
  });
  const watchedPrimaryLanguage = useWatch({
    control: form.control,
    name: "primary_language",
  });
  const watchedSupportedLanguages = useWatch({
    control: form.control,
    name: "supported_languages",
  });
  
  async function onSubmit(values: AgentConfigFormValues) {
    setSaving(true);
    try {
      const res = await fetch(
        `${process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000"}/agents/config`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(values),
        },
      );

      if (!res.ok) {
        const body = (await res.json().catch(() => ({}))) as {
          detail?: string;
        };
        throw new ApiError(res.status, body.detail ?? res.statusText);
      }

      const updated = (await res.json()) as {
        success: boolean;
        data: AgentConfig;
      };

      reset({
        agent_name: updated.data.agent_name,
        company_name: updated.data.company_name,
        company_info: updated.data.company_info,
        objective: updated.data.objective,
        personality: updated.data.personality,
        greeting_template: updated.data.greeting_template,
        max_call_duration_seconds: updated.data.max_call_duration_seconds,
        primary_language: updated.data.primary_language,
        supported_languages: updated.data.supported_languages,
        voice_overrides: updated.data.voice_overrides,
      });

      router.refresh();
      toast.success("Agent configuration saved");
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.detail
          : "Failed to save. Check the server logs.";
      toast.error(message);
    } finally {
      setSaving(false);
    }
  }

  function onReset() {
    reset();
    toast.info("Changes discarded");
  }

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="space-y-8">
      <div className="rounded-lg border bg-card p-6">
        <FieldGroup>
          <Field>
            <FieldLabel htmlFor="agent_name">Agent name</FieldLabel>
            <Input id="agent_name" {...register("agent_name")} />
            <FieldDescription>
              The persona name the agent uses when introducing itself.
            </FieldDescription>
            {errors.agent_name && (
              <FieldError>{errors.agent_name.message}</FieldError>
            )}
          </Field>

          <Field>
            <FieldLabel htmlFor="company_name">Company name</FieldLabel>
            <Input id="company_name" {...register("company_name")} />
            {errors.company_name && (
              <FieldError>{errors.company_name.message}</FieldError>
            )}
          </Field>

          <Field>
            <FieldLabel htmlFor="company_info">Company information</FieldLabel>
            <Textarea
              id="company_info"
              rows={3}
              {...register("company_info")}
            />
            <FieldDescription>
              Background the agent can reference during the conversation.
            </FieldDescription>
            {errors.company_info && (
              <FieldError>{errors.company_info.message}</FieldError>
            )}
          </Field>

          <Field>
            <FieldLabel htmlFor="objective">Objective of the call</FieldLabel>
            <Textarea id="objective" rows={2} {...register("objective")} />
            {errors.objective && (
              <FieldError>{errors.objective.message}</FieldError>
            )}
          </Field>

          <Field>
            <FieldLabel htmlFor="personality">
              Personality / system prompt
            </FieldLabel>
            <Textarea
              id="personality"
              rows={3}
              {...register("personality")}
            />
            <FieldDescription>
              Describes tone and style. Appended to the agent&apos;s system
              prompt.
            </FieldDescription>
            {errors.personality && (
              <FieldError>{errors.personality.message}</FieldError>
            )}
          </Field>

          <Field>
            <FieldLabel htmlFor="greeting_template">
              Greeting template
            </FieldLabel>
            <Textarea
              id="greeting_template"
              rows={3}
              {...register("greeting_template")}
            />
            <FieldDescription>
              Use <code>{"{name}"}</code> and <code>{"{company}"}</code> as
              placeholders. They are substituted at call time.
            </FieldDescription>
            {errors.greeting_template && (
              <FieldError>{errors.greeting_template.message}</FieldError>
            )}
          </Field>
        </FieldGroup>
      </div>

      <GreetingPreview
        template={watchedGreeting}
        agentName={watchedName}
        companyName={watchedCompany}
      />

      <div className="rounded-lg border bg-card p-6">
        <FieldGroup>
          <Field>
            <FieldLabel htmlFor="max_call_duration_seconds">
              Maximum call duration (seconds)
            </FieldLabel>
            <Input
              id="max_call_duration_seconds"
              type="number"
              min={30}
              max={3600}
              {...register("max_call_duration_seconds", {
                valueAsNumber: true,
              })}
            />
            {errors.max_call_duration_seconds && (
              <FieldError>
                {errors.max_call_duration_seconds.message}
              </FieldError>
            )}
          </Field>

          <Field>
            <FieldLabel htmlFor="primary_language">
              Primary language
            </FieldLabel>
            <Select
              value={watchedPrimaryLanguage}
              onValueChange={(value) => {
                // Base UI's Select emits string | null because its
                // model allows a clearable selection. Ours always
                // has a value, so null never arrives at runtime.
                // The guard satisfies the type and is a no-op.
                if (value === null) return;
                form.setValue("primary_language", value, {
                  shouldDirty: true,
                });
              }}
            >              
            <SelectTrigger id="primary_language">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {LANGUAGE_CODES.map((code) => (
                  <SelectItem key={code} value={code}>
                    {code}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {errors.primary_language && (
              <FieldError>{errors.primary_language.message}</FieldError>
            )}
          </Field>

          <Field>
            <FieldLabel>Supported languages</FieldLabel>
            <FieldDescription>
              All languages this agent can handle. The backend accepts
              only registered codes.
            </FieldDescription>
            <div className="flex flex-wrap gap-3 pt-2">
              {LANGUAGE_CODES.map((code) => {
                const checked = watchedSupportedLanguages.includes(code);
                return (
                  <label
                    key={code}
                    className="flex items-center gap-2 text-sm"
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={(e) => {
                        const next = e.target.checked
                          ? [...watchedSupportedLanguages, code]
                          : watchedSupportedLanguages.filter(
                              (c) => c !== code,
                            );
                        form.setValue("supported_languages", next, {
                          shouldDirty: true,
                          shouldValidate: true,
                        });
                      }}                      
                      className="h-4 w-4 rounded border-border"
                    />
                    {code}
                  </label>
                );
              })}
            </div>
            {errors.supported_languages && (
              <FieldError>{errors.supported_languages.message}</FieldError>
            )}
          </Field>
        </FieldGroup>
      </div>

      <div className="flex items-center gap-3">
        <Button type="submit" disabled={saving || !isDirty}>
          {saving ? (
            <>
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              Saving…
            </>
          ) : (
            <>
              <Save className="mr-2 h-4 w-4" />
              Save changes
            </>
          )}
        </Button>
        <Button
          type="button"
          variant="outline"
          onClick={onReset}
          disabled={saving || !isDirty}
        >
          <RotateCcw className="mr-2 h-4 w-4" />
          Discard
        </Button>
        {isDirty && (
          <span className="text-xs text-muted-foreground">
            Unsaved changes
          </span>
        )}
      </div>
    </form>
  );
}
