import { errorMessage } from "@/lib/api";

describe("errorMessage", () => {
  it("shows the API's detail text", () => {
    expect(errorMessage(402, '{"detail":"Paid plan required"}')).toBe("Paid plan required");
  });

  it("never shows a proxy's HTML error page", () => {
    const html = "<!DOCTYPE html><html><title>502: Bad gateway</title></html>";
    expect(errorMessage(502, html)).toBe(
      "HalalLens is briefly unavailable. Please try again in a minute.",
    );
  });

  it("falls back to the status when the detail is not text", () => {
    expect(errorMessage(422, '{"detail":[{"loc":["body"]}]}')).toBe("Request failed (422).");
  });
});
