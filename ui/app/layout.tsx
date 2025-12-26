import "./globals.css";
import { ReactNode } from "react";
import { AuthProvider } from "@/providers/AuthProvider";

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
      </body>
    </html>
  );
}
