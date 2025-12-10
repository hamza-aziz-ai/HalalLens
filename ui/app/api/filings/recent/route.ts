import { NextRequest, NextResponse } from "next/server";

const API_BASE =
  process.env.HALAL_API_BASE_URL ||
  process.env.NEXT_PUBLIC_HALAL_API_BASE_URL ||
  "http://localhost:8000";

export async function GET(req: NextRequest) {
  const limit = req.nextUrl.searchParams.get("limit") ?? "20";
  const upstream = await fetch(
    `${API_BASE}/filings/recent?limit=${encodeURIComponent(limit)}`,
    { cache: "no-store" },
  );
  if (!upstream.ok) {
    const detail = await upstream.text();
    return NextResponse.json(
      { error: detail || "Failed to load filings" },
      { status: upstream.status },
    );
  }
  const payload = await upstream.json();
  return NextResponse.json(payload);
}
