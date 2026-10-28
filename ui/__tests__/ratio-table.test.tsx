import { render, screen } from "@testing-library/react";
import { RatioTable } from "@/components/ratio-table";
import type { HalalScoreResponse } from "@/lib/types";

function evaluation(overrides: Partial<HalalScoreResponse>): HalalScoreResponse {
  return {
    symbol: "TCS",
    filing_date: "2024-06-30T00:00:00",
    is_compliant: true,
    screen_verdict: "compliant",
    ratios: {},
    missing_inputs: {},
    ...overrides,
  };
}

describe("RatioTable verdict badge", () => {
  it("shows Compliant", () => {
    render(<RatioTable evaluation={evaluation({})} />);
    expect(screen.getByText("Compliant")).toBeInTheDocument();
  });

  it("shows Non-compliant", () => {
    render(
      <RatioTable
        evaluation={evaluation({ is_compliant: false, screen_verdict: "non-compliant" })}
      />,
    );
    expect(screen.getByText("Non-compliant")).toBeInTheDocument();
  });

  it("shows Insufficient data, never Non-compliant, for a null verdict", () => {
    render(
      <RatioTable
        evaluation={evaluation({
          is_compliant: null,
          screen_verdict: "insufficient-data",
          missing_inputs: { interest_income: "missing" },
        })}
      />,
    );
    expect(screen.getByText("Insufficient data")).toBeInTheDocument();
    expect(screen.queryByText("Non-compliant")).not.toBeInTheDocument();
    expect(screen.getByText(/interest income: missing/i)).toBeInTheDocument();
  });
});
