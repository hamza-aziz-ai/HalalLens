import { render, screen } from "@testing-library/react";

import GithubBadge from "@/components/github-badge";

describe("GithubBadge", () => {
  const original = process.env.NEXT_PUBLIC_REPO_URL;
  afterEach(() => {
    process.env.NEXT_PUBLIC_REPO_URL = original;
  });

  it("links to the configured repository in a new tab", () => {
    process.env.NEXT_PUBLIC_REPO_URL = "https://github.com/example/repo";
    render(<GithubBadge />);
    const link = screen.getByRole("link", { name: "Source code on GitHub" });
    expect(link).toHaveAttribute("href", "https://github.com/example/repo");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });

  it.each(["", "none", "javascript:alert(1)"])("renders nothing for %p", (value) => {
    process.env.NEXT_PUBLIC_REPO_URL = value;
    const { container } = render(<GithubBadge />);
    expect(container).toBeEmptyDOMElement();
  });
});
