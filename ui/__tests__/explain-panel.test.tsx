import { render, screen } from "@testing-library/react";
import { ExplainPanel } from "@/components/explain-panel";
import type { NarrationResponse } from "@/lib/types";

function narration(overrides: Partial<NarrationResponse>): NarrationResponse {
  return {
    symbol: "TCS",
    filing_date: "2024-06-30T00:00:00",
    is_compliant: true,
    screen_verdict: "compliant",
    summary: "All inside the caps.",
    verdict: "compliant with AAOIFI screens",
    bullets: ["Debt to market cap is 12.50% vs 30% cap."],
    citations: ["Filing date: 2024-06-30"],
    source: "rule_based",
    ...overrides,
  };
}

describe("ExplainPanel", () => {
  it("shows no AI caveat for the rule-based narrator", () => {
    render(<ExplainPanel narration={narration({})} />);
    expect(screen.queryByTestId("ai-caveat")).not.toBeInTheDocument();
  });

  it("warns that LLM text is AI-generated and the badge is authoritative", () => {
    render(<ExplainPanel narration={narration({ source: "llm" })} />);
    const caveat = screen.getByTestId("ai-caveat");
    expect(caveat).toHaveTextContent(/AI-generated/i);
    expect(caveat).toHaveTextContent(/authoritative/i);
  });
});
