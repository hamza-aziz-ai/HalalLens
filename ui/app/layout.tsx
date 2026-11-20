import "./globals.css";
import { ReactNode } from "react";
import type { Metadata } from "next";
import { IBM_Plex_Mono, IBM_Plex_Sans } from "next/font/google";
import { AuthProvider } from "@/providers/AuthProvider";
import { ThemeProvider } from "@/providers/ThemeProvider";
import MaintenanceOverlay from "@/components/maintenance-overlay";
import GithubBadge from "@/components/github-badge";

// Self-hosted at build time: no request to Google's font CDN from the browser.
const sans = IBM_Plex_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-sans",
  display: "swap",
});
const mono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: {
    default: "HalalLens: Shariah screening for Indian equities",
    template: "%s | HalalLens",
  },
  description:
    "Screen BSE-listed Indian companies against AAOIFI-inspired financial ratios and read why each verdict was reached.",
};

// Runs before the first paint so the page never flashes the wrong theme.
// Same rule as readTheme in providers/ThemeProvider.tsx.
const THEME_SCRIPT = `try{var t=localStorage.getItem("halal-lens-theme");if(t!=="light"&&t!=="dark"){t=matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light"}document.documentElement.dataset.theme=t}catch(e){}`;

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={`${sans.variable} ${mono.variable}`} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
      </head>
      <body>
        <ThemeProvider>
          <AuthProvider>{children}</AuthProvider>
          <GithubBadge />
          <MaintenanceOverlay />
        </ThemeProvider>
      </body>
    </html>
  );
}
