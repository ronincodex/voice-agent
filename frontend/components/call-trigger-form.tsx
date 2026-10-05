"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Loader2, PhoneCall } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
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
import { ApiError, BROWSER_HEADERS } from "@/lib/api";

interface LanguageEntry {
  code: string;
  name: string;
}

/**
 * Phone number in E.164 form. Allows 8 to 15 digits after the
 * leading +, which covers every country code. Rejects whitespace,
 * dashes, and anything else that would not survive the round trip
 * to Vobiz.
 */
const E164_PATTERN = /^\+\d{8,15}$/;

export function CallTriggerForm({
  languages,
  defaultLanguage,
}: {
  languages: LanguageEntry[];
  defaultLanguage: string;
}) {
  const router = useRouter();
  const [to, setTo] = useState("");
  const [language, setLanguage] = useState(defaultLanguage);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isValid = E164_PATTERN.test(to);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    if (!isValid) {
      setError("Enter a phone number in E.164 format, e.g. +919876543210");
      return;
    }

    setSubmitting(true);
    try {
      const res = await fetch(
        `${process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000"}/call`,
        {
          method: "POST",
          headers: { ...BROWSER_HEADERS, "Content-Type": "application/json" },
          body: JSON.stringify({ to, language }),
        },
      );

      if (!res.ok) {
        const body = (await res.json().catch(() => ({}))) as {
          detail?: string;
        };
        throw new ApiError(res.status, body.detail ?? res.statusText);
      }

      toast.success(`Calling ${to}…`, {
        description: "The call will appear in the list within a few seconds.",
        action: {
          label: "View calls",
          onClick: () => router.push("/calls"),
        },
      });

      // Clear the field so the operator can dial the next number.
      setTo("");
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.detail
          : "Failed to start the call. Check the server logs.";
      setError(message);
      toast.error("Call failed", { description: message });
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Card>
      <CardContent className="pt-6">
        <form onSubmit={onSubmit} className="space-y-6">
          <FieldGroup>
            <Field>
              <FieldLabel htmlFor="to">Phone number</FieldLabel>
              <Input
                id="to"
                type="tel"
                placeholder="+919876543210"
                value={to}
                onChange={(e) => {
                  setTo(e.target.value.trim());
                  setError(null);
                }}
                disabled={submitting}
                autoComplete="off"
              />
              <FieldDescription>
                E.164 format: a leading + followed by the country code and
                number. For India, +91 then the 10-digit mobile number.
              </FieldDescription>
              {error && <FieldError>{error}</FieldError>}
            </Field>

            <Field>
              <FieldLabel htmlFor="language">Language</FieldLabel>
              <Select
                value={language}
                onValueChange={(value) => {
                  if (value === null) return;
                  setLanguage(value);
                }}
                disabled={submitting}
              >
                <SelectTrigger id="language">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {languages.map((lang) => (
                    <SelectItem key={lang.code} value={lang.code}>
                      {lang.name} ({lang.code})
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <FieldDescription>
                The agent speaks this language for the entire call.
              </FieldDescription>
            </Field>
          </FieldGroup>

          <Button
            type="submit"
            disabled={submitting || !isValid}
            className="w-full"
            size="lg"
          >
            {submitting ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Starting call…
              </>
            ) : (
              <>
                <PhoneCall className="mr-2 h-4 w-4" />
                Start call
              </>
            )}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
