import { render, screen } from "@testing-library/react";
import { ProviderBadge } from "@/components/provider-badge";

describe("ProviderBadge", () => {
  it("renders manual label by default", () => {
    render(<ProviderBadge />);
    expect(screen.getByText(/Manual input/i)).toBeInTheDocument();
  });

  it("shows auto provider label", () => {
    render(<ProviderBadge provider="indianapi" />);
    expect(screen.getByText(/Indian Stock API/i)).toBeInTheDocument();
  });
});
