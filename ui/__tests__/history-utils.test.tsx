import { mergeHistoryEntries } from "@/lib/history";
import type { Filing } from "@/lib/types";

const sample = (overrides?: Partial<Filing>): Filing => ({
  symbol: "TCS",
  company_name: "Tata Consultancy Services",
  filing_date: new Date("2024-06-30T00:00:00Z").toISOString(),
  category: "Result",
  headline: "Results",
  confidence: "HIGH",
  total_debt: 100,
  cash_equiv: 50,
  revenue: 100,
  interest_income: 5,
  dividend_income: 2,
  audit_status: "audited",
  ratios: {},
  accounts_receivable: 10,
  liquid_assets: 25,
  non_halal_income: 1,
  market_cap_used: 1000,
  trailing_cap_used: null,
  market_data_provider: "ingestion",
  quality_issues: [],
  ...overrides,
});

describe("mergeHistoryEntries", () => {
  it("appends new unique entries and keeps descending order", () => {
    const first = sample();
    const second = sample({ filing_date: new Date("2024-03-31Z").toISOString() });
    const merged = mergeHistoryEntries([first], [second]);
    expect(merged).toHaveLength(2);
    expect(merged[0].filing_date).toBe(first.filing_date);
    expect(merged[1].filing_date).toBe(second.filing_date);
  });

  it("deduplicates entries by symbol/date", () => {
    const first = sample();
    const duplicate = sample({ revenue: 900 });
    const merged = mergeHistoryEntries([first], [duplicate]);
    expect(merged).toHaveLength(1);
    expect(merged[0].revenue).toBe(100); // existing entry preserved
  });
});
