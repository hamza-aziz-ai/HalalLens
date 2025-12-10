import "./globals.css";
import { ReactNode } from "react";

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
      <body className="min-h-screen bg-slate-950 text-slate-100">
        <div className="mx-auto max-w-6xl px-4 py-10">{children}</div>
      </body>
    </html>
  );
}
