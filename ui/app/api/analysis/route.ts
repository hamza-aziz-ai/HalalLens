import { NextRequest, NextResponse } from "next/server";
import { z } from "zod";

const payloadSchema = z.object({
  snapshot: z.object({
    symbol: z.string(),
    filing_date: z.string(),
    total_debt: z.number().optional(),
    cash_equiv: z.number().optional(),
    revenue: z.number().optional(),
    interest_income: z.number().optional(),
    dividend_income: z.number().optional(),
    non_permissible_income: z.number().optional(),
  }),
  market_data: z.object({
    market_cap: z.number().optional(),
    trailing_market_cap: z.number().optional(),
  }),
});

const API_BASE =
  process.env.HALAL_API_BASE_URL ?? "http://localhost:8000";

export async function POST(req: NextRequest) {
  const body = await req.json();
  const parsed = payloadSchema.safeParse(body);
  if (!parsed.success) {
    return NextResponse.json(
      { error: parsed.error.flatten() },
      { status: 422 },
    );
  }

  const payload = parsed.data;
  const [scoreRes, narrateRes] = await Promise.all([
    fetch(`${API_BASE}/halal-score`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
    fetch(`${API_BASE}/narrate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  ]);

  if (!scoreRes.ok) {
    const detail = await scoreRes.text();
    return NextResponse.json({ error: detail }, { status: scoreRes.status });
  }
  if (!narrateRes.ok) {
    const detail = await narrateRes.text();
    return NextResponse.json(
      { error: detail },
      { status: narrateRes.status },
    );
  }

  const [score, narration] = await Promise.all([
    scoreRes.json(),
    narrateRes.json(),
  ]);

  return NextResponse.json({ score, narration });
}
