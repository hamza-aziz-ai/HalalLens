import { NextRequest, NextResponse } from "next/server";

const API_BASE =
  process.env.HALAL_API_BASE_URL ||
  process.env.NEXT_PUBLIC_HALAL_API_BASE_URL ||
  "http://localhost:8000";

export async function GET(req: NextRequest) {
  const userId = req.nextUrl.searchParams.get("user_id");
  if (!userId) {
    return NextResponse.json(
      { error: "user_id query param required" },
      { status: 400 },
    );
  }
  const upstream = await fetch(
    `${API_BASE}/watchlist/${encodeURIComponent(userId)}`,
    { cache: "no-store" },
  );
  if (!upstream.ok) {
    const detail = await upstream.text();
    return NextResponse.json(
      { error: detail || "Failed to load watchlist" },
      { status: upstream.status },
    );
  }
  const payload = await upstream.json();
  return NextResponse.json(payload);
}

export async function POST(req: NextRequest) {
  const body = await req.json();
  const upstream = await fetch(`${API_BASE}/watchlist`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!upstream.ok) {
    const detail = await upstream.text();
    return NextResponse.json(
      { error: detail || "Failed to upsert watchlist entry" },
      { status: upstream.status },
    );
  }
  const payload = await upstream.json();
  return NextResponse.json(payload);
}
