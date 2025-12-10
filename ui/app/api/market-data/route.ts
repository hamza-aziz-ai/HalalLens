import { NextRequest, NextResponse } from "next/server";

const API_BASE =
  process.env.HALAL_API_BASE_URL ||
  process.env.NEXT_PUBLIC_HALAL_API_BASE_URL ||
  "http://localhost:8000";

export async function GET(req: NextRequest) {
  const symbol = req.nextUrl.searchParams.get("symbol");
  if (!symbol) {
    return NextResponse.json(
      { error: "symbol query param required" },
      { status: 400 },
    );
  }
  const upstream = await fetch(
    `${API_BASE}/market-data/${encodeURIComponent(symbol)}`,
    { cache: "no-store" },
  );

  if (!upstream.ok) {
    const detail = await upstream.text();
    return NextResponse.json(
      { error: detail || "Failed to fetch market data" },
      { status: upstream.status },
    );
  }
  const payload = await upstream.json();
  return NextResponse.json(payload);
}
