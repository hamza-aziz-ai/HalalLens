import "./globals.css";
import { ReactNode } from "react";
import { AuthProvider } from "@/providers/AuthProvider";
import MaintenanceOverlay from "@/components/maintenance-overlay";
import GithubBadge from "@/components/github-badge";

export const metadata = {
  title: "HalalLens",
  description: "Shariah compliance insights for equities and mutual funds",
};

export default function RootLayout({
  children,
}: {
  children: ReactNode;
}) {
  return (
    <html lang="en">
      <body className="bg-slate-950 text-slate-100">
        <AuthProvider>{children}</AuthProvider>
        <GithubBadge />
        <MaintenanceOverlay />
      </body>
    </html>
  );
}
