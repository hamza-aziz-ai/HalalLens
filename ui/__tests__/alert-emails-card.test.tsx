import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { AlertEmailsCard } from "@/components/alert-emails-card";
import { fetchAlertEmails, saveAlertEmails } from "@/lib/alerts";

jest.mock("@/lib/alerts", () => ({
  fetchAlertEmails: jest.fn(async () => true),
  saveAlertEmails: jest.fn(async (enabled: boolean) => enabled),
}));

const props = { cardClass: "", headingClass: "", mutedTextClass: "" };

describe("AlertEmailsCard", () => {
  it("shows the stored setting and saves the opt-out", async () => {
    render(<AlertEmailsCard {...props} />);
    const box = screen.getByRole("checkbox", { name: /email me when a watched stock/i });
    await waitFor(() => expect(box).toBeChecked());
    expect(screen.getByText(/not a fatwa and not investment advice/i)).toBeInTheDocument();

    fireEvent.click(box);
    await waitFor(() => expect(box).not.toBeChecked());
    expect(saveAlertEmails).toHaveBeenCalledWith(false);
  });

  it("stays disabled and says so when the setting cannot be loaded", async () => {
    (fetchAlertEmails as jest.Mock).mockRejectedValueOnce(new Error("Invalid session"));
    render(<AlertEmailsCard {...props} />);
    expect(await screen.findByText("Invalid session")).toBeInTheDocument();
    expect(screen.getByRole("checkbox")).toBeDisabled();
  });
});
