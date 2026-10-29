import { callAnalysis } from "@/lib/api";
import type { AnalysisPayload } from "@/lib/types";

const payload = {} as AnalysisPayload;
const score = { verdict: "compliant" };

function respond(status: number, body: unknown) {
  return Promise.resolve({
    ok: status < 400,
    status,
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  } as Response);
}

describe("callAnalysis", () => {
  const fetchMock = jest.fn();
  // The client logger also posts errors to /client-logs; count API calls only.
  const apiCalls = () =>
    fetchMock.mock.calls.map(([url]) => String(url)).filter((url) => !url.endsWith("/client-logs"));

  beforeEach(() => {
    fetchMock.mockReset();
    global.fetch = fetchMock as unknown as typeof fetch;
  });

  it("does not call the paid /narrate when narration is not included", async () => {
    fetchMock.mockImplementation(() => respond(200, score));
    const result = await callAnalysis(payload, false);
    expect(result).toEqual({ score, narration: null });
    expect(apiCalls()).toEqual([expect.stringMatching(/\/halal-score$/)]);
  });

  it("keeps the score when /narrate fails", async () => {
    fetchMock.mockImplementation((url: string) =>
      url.endsWith("/narrate") ? respond(402, { detail: "Paid plan required" }) : respond(200, score),
    );
    const result = await callAnalysis(payload, true);
    expect(result).toEqual({ score, narration: null });
    expect(apiCalls()).toHaveLength(2);
  });
});
