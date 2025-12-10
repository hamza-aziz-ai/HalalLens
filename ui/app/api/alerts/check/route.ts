import { NextRequest, NextResponse } from "next/server";

const API_BASE =
  process.env.HALAL_API_BASE_URL ||
  process.env.NEXT_PUBLIC_HALAL_API_BASE_URL ||
  "http://localhost:8000";

export async function POST(req: NextRequest) {
  const body = await req.json();
  const upstream = await fetch(`${API_BASE}/alerts/check`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!upstream.ok) {
    const detail = await upstream.text();
    return NextResponse.json(
      { error: detail || "Alert processing failed" },
      { status: upstream.status },
    );
  }
  const payload = await upstream.json();
  return NextResponse.json(payload);
}
