import { Toaster } from "@/components/ui/sonner";
import { NuqsAdapter } from "nuqs/adapters/next/app";
import type { Metadata } from "next";
import { Geist } from "next/font/google";

import { AppSidebar } from "@/components/app-sidebar";
import { cn } from "@/lib/utils";

import "./globals.css";

const geist = Geist({ subsets: ["latin"], variable: "--font-sans" });

export const metadata: Metadata = {
  title: "Voice Agent: IT-Webhut",
  description: "AI voice calling agent for IT-Webhut",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={cn("font-sans", geist.variable)}>
           <body className="antialiased">
        {/* NuqsAdapter connects nuqs' useQueryState hooks to the
            Next.js App Router. Without it, useQueryState throws at
            runtime with "no adapter found". One wrapper for the
            whole app; every Client Component that reads or writes
            URL params needs it. */}
        <NuqsAdapter>
          <div className="flex min-h-screen bg-background">
            <AppSidebar />
            <main className="flex-1 p-6 lg:p-8">{children}</main>
          </div>
        </NuqsAdapter>
        <Toaster />
      </body>   
</html>
  );
}
