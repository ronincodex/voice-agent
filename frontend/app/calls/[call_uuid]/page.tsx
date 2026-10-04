import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ChevronLeft } from "lucide-react";

import { CallAudioPlayer } from "@/components/call-audio-player";
import { CallMetadata } from "@/components/call-metadata";
import { CallTranscript } from "@/components/call-transcript";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { ApiError, fetchApi } from "@/lib/api";
import type { CallDetail } from "@/lib/types";

interface PageProps {
  params: Promise<{ call_uuid: string }>;
}

/**
 * Fetch one call. Used by both generateMetadata and the page
 * component. Next.js memoizes fetch calls with the same URL within
 * a single render pass, so calling this twice does not make two
 * network requests — the second call reuses the first's result.
 */
async function getCall(callUuid: string): Promise<CallDetail | null> {
  try {
    return await fetchApi<CallDetail>(`/calls/${callUuid}`);
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) {
      return null;
    }
    throw err;
  }
}

export async function generateMetadata({
  params,
}: PageProps): Promise<Metadata> {
  const { call_uuid } = await params;
  const call = await getCall(call_uuid);

  if (!call) {
    return { title: "Call not found — Voice Agent" };
  }

  const direction = call.direction === "inbound" ? "Inbound" : "Outbound";
  const when = new Date(call.started_at).toLocaleString("en-IN", {
    dateStyle: "medium",
    timeStyle: "short",
  });

  return {
    title: `${direction} call · ${when} — Voice Agent`,
    description: call.summary?.summary ?? `Call recording for ${call_uuid}`,
  };
}

export default async function CallDetailPage({ params }: PageProps) {
  const { call_uuid } = await params;
  const call = await getCall(call_uuid);

  if (!call) {
    notFound();
  }

  return (
    <div className="space-y-6">
        <div>
        <Link
          href="/calls"
          className={cn(
            buttonVariants({ variant: "ghost", size: "sm" }),
            "-ml-3 mb-2",
          )}
        >
          <ChevronLeft className="mr-1 h-4 w-4" />
          All calls
        </Link>
        <h2 className="text-2xl font-semibold tracking-tight">
          Call detail
        </h2>        
        <p className="font-mono text-xs text-muted-foreground">
          {call.call_uuid}
        </p>
      </div>

      <CallMetadata call={call} />

      {call.recording_url && <CallAudioPlayer callUuid={call.call_uuid} />}

      <CallTranscript messages={call.messages} />
    </div>
  );
}
