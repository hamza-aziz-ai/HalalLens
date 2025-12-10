const API_BASE =
  process.env.HALAL_API_BASE_URL ||
  process.env.NEXT_PUBLIC_HALAL_API_BASE_URL ||
  "http://localhost:8000";

export async function GET() {
  const upstream = await fetch(`${API_BASE}/ingestion/stats`, {
    cache: "no-store",
  });
  if (!upstream.ok) {
    const detail = await upstream.text();
    return new Response(
      JSON.stringify({ error: detail || "Failed to fetch stats" }),
      { status: upstream.status },
    );
  }
  const payload = await upstream.json();
  return new Response(JSON.stringify(payload));
}
