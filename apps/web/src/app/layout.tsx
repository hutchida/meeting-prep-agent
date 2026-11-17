import type { ReactNode } from "react";
import "./globals.css";

export const metadata = {
  title: "Meeting Prep Agent",
  description: "Cited meeting briefing packs from a hand-built multi-agent system",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-slate-50 text-slate-900 antialiased">{children}</body>
    </html>
  );
}
