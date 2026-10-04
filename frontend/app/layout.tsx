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
        <div className="flex min-h-screen bg-background">
          <AppSidebar />
          <main className="flex-1 p-6 lg:p-8">{children}</main>
        </div>
      </body>
    </html>
  );
}
