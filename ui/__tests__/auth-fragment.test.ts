import { takeFragmentParam } from "@/lib/auth";

describe("takeFragmentParam", () => {
  it("reads a proof from the fragment and clears it from the URL", () => {
    window.history.replaceState(null, "", "/reset/#reset=abc123");
    expect(takeFragmentParam("reset")).toBe("abc123");
    expect(window.location.hash).toBe("");
    expect(window.location.pathname).toBe("/reset/");
  });

  it("ignores the query string and other parameters", () => {
    window.history.replaceState(null, "", "/verify/?signup=from-query#other=1");
    expect(takeFragmentParam("signup")).toBeNull();
    expect(window.location.hash).toBe("#other=1");
  });
});
