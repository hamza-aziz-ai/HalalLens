import { render, screen } from "@testing-library/react";
import RatioGauge from "@/components/ratio-gauge";
import SampleScreening from "@/components/sample-screening";

test("a ratio over its cap crosses the cap marker and says so in text", () => {
  const { container } = render(
    <RatioGauge label="Debt" value={0.65} threshold={0.3} passed={false} />,
  );
  expect(screen.getByText("65.00%")).toBeInTheDocument();
  expect(screen.getByText("(over the cap)", { exact: false })).toBeInTheDocument();
  const [, fill, cap] = Array.from(container.querySelectorAll<HTMLElement>("[aria-hidden] , [aria-hidden] *"));
  expect(fill.style.width).toBe("100%");
  expect(parseFloat(cap.style.left)).toBeLessThan(100);
});

test("every sample card says it is fictional", () => {
  render(<SampleScreening />);
  expect(screen.getAllByText(/fictional company · not live screening/i)).toHaveLength(2);
});
