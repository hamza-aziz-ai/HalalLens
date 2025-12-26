import { fetchFilingHistory } from "@/lib/filings";
import { request } from "@/lib/api";

jest.mock("@/lib/api", () => ({
  request: jest.fn(),
}));

const mockedRequest = request as jest.MockedFunction<typeof request>;

describe("fetchFilingHistory", () => {
  beforeEach(() => {
    mockedRequest.mockResolvedValue({ entries: [], next_cursor: null });
  });

  it("requests default page size", async () => {
    await fetchFilingHistory("TCS");
    expect(mockedRequest).toHaveBeenCalledWith("/filings/TCS/history?limit=12");
  });

  it("includes cursor parameter when provided", async () => {
    await fetchFilingHistory("TCS", { limit: 5, cursor: "2024-06-30T00:00:00Z" });
    expect(mockedRequest).toHaveBeenCalledWith(
      "/filings/TCS/history?limit=5&cursor=2024-06-30T00%3A00%3A00Z",
    );
  });
});
