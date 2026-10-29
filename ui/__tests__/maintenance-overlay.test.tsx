import { act, render, screen } from "@testing-library/react";

import MaintenanceOverlay from "@/components/maintenance-overlay";
import { isOutageResponse, reportOutage } from "@/lib/outage";

describe("isOutageResponse", () => {
  it("treats restarts and Cloudflare origin errors as an outage", () => {
    expect(isOutageResponse(503, "30")).toBe(true); // Caddy or Worker maintenance answer
    expect(isOutageResponse(530, null)).toBe(true); // tunnel down
    expect(isOutageResponse(502, null)).toBe(true);
    expect(isOutageResponse(522, null)).toBe(true);
  });

  it("keeps the API's own errors as ordinary errors", () => {
    expect(isOutageResponse(503, null)).toBe(false); // e.g. "Checkout is unavailable"
    expect(isOutageResponse(500, null)).toBe(false);
    expect(isOutageResponse(402, null)).toBe(false);
  });
});

describe("MaintenanceOverlay", () => {
  const fetchMock = jest.fn();
  const reload = jest.fn();

  beforeEach(() => {
    jest.useFakeTimers();
    fetchMock.mockReset();
    reload.mockReset();
    global.fetch = fetchMock as unknown as typeof fetch;
    Object.defineProperty(window, "location", { value: { reload }, writable: true });
  });

  afterEach(() => jest.useRealTimers());

  const answer = (ok: boolean) => fetchMock.mockImplementation(() => Promise.resolve({ ok } as Response));

  it("appears when an outage is reported and confirmed, then reloads once the site is back", async () => {
    answer(false);
    render(<MaintenanceOverlay />);
    await act(async () => reportOutage());
    expect(await screen.findByRole("alertdialog")).toBeTruthy();

    answer(true);
    await act(async () => {
      jest.advanceTimersByTime(5_000);
    });
    expect(reload).toHaveBeenCalled();
  });

  it("stays hidden when the health check says the site is up", async () => {
    answer(true);
    render(<MaintenanceOverlay />);
    await act(async () => reportOutage());
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });

  it("appears on its own through the heartbeat, without any API call", async () => {
    answer(false);
    render(<MaintenanceOverlay />);
    await act(async () => {
      jest.advanceTimersByTime(30_000);
    });
    expect(await screen.findByRole("alertdialog")).toBeTruthy();
  });
});
