import { render, screen, fireEvent } from "@testing-library/react";
import { GovernanceReviewPanel } from "@/components/governance-review";
import type { GovernanceReview } from "@/lib/types";

const sampleReview: GovernanceReview = {
  symbol: "TCS",
  filing_date: "2024-06-30T00:00:00Z",
  ingested: {
    label: "Ingested",
    source: "ingestion",
    metrics: {
      accounts_receivable: 120,
      liquid_assets: 90,
      non_halal_income: 3,
    },
  },
  override: {
    label: "Override",
    source: "manual",
    metrics: {
      accounts_receivable: 130,
      liquid_assets: 95,
      non_halal_income: 2.5,
    },
  },
  indian_api: {
    label: "Indian API",
    source: "indianapi",
    metrics: {
      accounts_receivable: 150,
      liquid_assets: 110,
      non_halal_income: 2,
    },
  },
  differences: {
    accounts_receivable: {
      override_delta: 0.0833,
      indian_delta: 0.25,
    },
  },
};

describe("GovernanceReviewPanel", () => {
  it("renders metrics and deltas", () => {
    render(
      <GovernanceReviewPanel
        review={sampleReview}
        theme="dark"
      />,
    );

    expect(screen.getByText("Accounts receivable")).toBeInTheDocument();
    expect(screen.getByText("Indian 25.0%")).toBeInTheDocument();
  });

  it("emits apply event when requested", () => {
    const onApply = jest.fn();
    render(
      <GovernanceReviewPanel
        review={sampleReview}
        theme="dark"
        onApplyIndian={onApply}
      />,
    );
    fireEvent.click(screen.getByText(/Apply Indian values/i));
    expect(onApply).toHaveBeenCalled();
  });
});
