import { render, screen, fireEvent } from "@testing-library/react";
import { RatioTrendChart } from "@/components/ratio-trend-chart";
import type { Filing } from "@/lib/types";

const sampleEntry = (overrides?: Partial<Filing>): Filing => ({
  symbol: "ABC",
  company_name: "ABC Ltd",
  filing_date: new Date("2024-06-30T00:00:00Z").toISOString(),
  category: "Result",
  headline: "Quarterly",
  confidence: "HIGH",
  total_debt: 10,
  cash_equiv: 10,
  revenue: 10,
  interest_income: 10,
  dividend_income: 0,
  accounts_receivable: 10,
  liquid_assets: 10,
  non_halal_income: 10,
  governance_notes: null,
  audit_status: "audited",
  is_compliant: true,
  verdict: "compliant",
  summary: "ok",
  narration_source: "api",
  ratios: {
    debt_to_market_cap: {
      value: 0.1,
      passed: true,
      threshold: 0.3,
      note: "",
    },
    cash_to_market_cap: {
      value: 0.2,
      passed: true,
      threshold: 0.3,
      note: "",
    },
    receivables_to_market_cap: {
      value: 0.3,
      passed: true,
      threshold: 0.67,
      note: "",
    },
    liquid_assets_to_market_cap: {
      value: 0.4,
      passed: true,
      threshold: 0.49,
      note: "",
    },
    non_permissible_income_ratio: {
      value: 0.01,
      passed: true,
      threshold: 0.05,
      note: "",
    },
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

describe("RatioTrendChart", () => {
  it("renders lines and headers", () => {
    render(
      <RatioTrendChart entries={[sampleEntry(), sampleEntry({ filing_date: new Date("2024-09-30").toISOString() })]} />,
    );
    expect(screen.getByText("Ratio trends")).toBeInTheDocument();
    expect(screen.getByText("Threshold view")).toBeInTheDocument();
  });

  it("invokes selection handler when a point is clicked", () => {
    const handleSelect = jest.fn();
    render(
      <RatioTrendChart
        entries={[sampleEntry(), sampleEntry({ filing_date: new Date("2024-09-30").toISOString() })]}
        onSelect={handleSelect}
      />,
    );
    const trigger = screen.getAllByLabelText(/Select filing/i)[0];
    fireEvent.click(trigger);
    expect(handleSelect).toHaveBeenCalled();
  });
});
