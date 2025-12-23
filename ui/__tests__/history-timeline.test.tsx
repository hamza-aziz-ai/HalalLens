import { render, screen, fireEvent } from "@testing-library/react";
import { HistoryTimeline } from "@/components/history-timeline";
import type { Filing } from "@/lib/types";

const ratio = (value: number | null, passed: boolean | null) => ({
  value,
  threshold: 0.3,
  passed,
  note: "test",
});

const baseEntry = (overrides?: Partial<Filing>): Filing => ({
  symbol: "TCS",
  company_name: "TCS",
  filing_date: new Date("2024-06-30T00:00:00Z").toISOString(),
  category: "Result",
  headline: "Quarterly",
  confidence: "HIGH",
  total_debt: 1,
  cash_equiv: 1,
  revenue: 1,
  interest_income: 1,
  dividend_income: 1,
  accounts_receivable: 1,
  liquid_assets: 1,
  non_halal_income: 1,
  governance_notes: null,
  audit_status: "audited",
  is_compliant: true,
  verdict: "compliant",
  summary: "All ratios pass.",
  narration_source: "api",
  ratios: {
    debt_to_market_cap: ratio(0.1, true),
    cash_to_market_cap: ratio(0.2, true),
    receivables_to_market_cap: ratio(0.3, true),
    liquid_assets_to_market_cap: ratio(0.4, true),
    non_permissible_income_ratio: ratio(0.01, true),
  },
  market_cap_used: 100,
  trailing_cap_used: null,
  market_data_provider: "yahoo",
  quality_issues: [],
  governance_override_applied: false,
  governance_override_source: null,
  governance_override_reason: null,
  governance_override_reviewer: null,
  governance_override_updated_at: null,
  ...overrides,
});

describe("HistoryTimeline", () => {
  it("renders entries and triggers selection callback", () => {
    const handleSelect = jest.fn();
    const entry = baseEntry();
    render(<HistoryTimeline entries={[entry]} onSelect={handleSelect} />);

    expect(screen.getByText("History & trends")).toBeInTheDocument();
    const buttons = screen.getAllByRole("button");
    fireEvent.click(buttons[0]);
    expect(handleSelect).toHaveBeenCalledWith(entry);
  });

  it("applies light theme styles when theme=light", () => {
    const entry = baseEntry();
    render(<HistoryTimeline entries={[entry]} theme="light" />);
    const heading = screen.getByText("History & trends");
    const article = heading.closest("article");
    expect(article).toHaveClass("bg-white");
  });

  it("shows missing ratio state when inputs unavailable", () => {
    const entry = baseEntry({
      ratios: {
        debt_to_market_cap: ratio(null, null),
        cash_to_market_cap: ratio(null, null),
        receivables_to_market_cap: ratio(null, null),
        liquid_assets_to_market_cap: ratio(null, null),
        non_permissible_income_ratio: ratio(null, null),
      },
    });
    render(<HistoryTimeline entries={[entry]} />);
    const missingBadges = screen.getAllByText("Missing inputs");
    expect(missingBadges.length).toBeGreaterThan(0);
  });
});
