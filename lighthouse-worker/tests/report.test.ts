import { describe, expect, it } from "vitest";

import { reportFromResult, type LighthouseRunResult } from "../src/report.js";

function lighthouseResult(): LighthouseRunResult {
  return {
    lhr: {
      requestedUrl: "https://example.com/page",
      mainDocumentUrl: "https://example.com/final-document",
      finalDisplayedUrl: "https://example.com/final",
      fetchTime: "2026-08-05T18:30:32.000Z",
      lighthouseVersion: "13.4.1",
      categories: {
        seo: {
          score: 0.75,
          auditRefs: [{ id: "shared" }, { id: "shared" }, { id: "perfect" }],
        },
        accessibility: { score: 0.5, auditRefs: [{ id: "shared" }] },
      },
      audits: {
        shared: {
          id: "shared",
          score: 0,
          scoreDisplayMode: "binary",
          title: "Shared finding",
          description: "Needs work",
          displayValue: "failed",
          numericValue: 1,
          numericUnit: "item",
        },
        perfect: {
          id: "perfect",
          score: 1,
          scoreDisplayMode: "binary",
          title: "Perfect",
          description: "Excluded",
        },
      },
    },
  } as unknown as LighthouseRunResult;
}

describe("Lighthouse report extraction", () => {
  it("deduplicates cross-category failures and excludes passing audits", () => {
    const report = reportFromResult(lighthouseResult(), [
      "seo",
      "accessibility",
    ]);

    expect(report.categories).toEqual({
      seo: { score: 0.75 },
      accessibility: { score: 0.5 },
    });
    expect(report.finalUrl).toBe("https://example.com/final-document");
    expect(report.findings).toEqual([
      {
        id: "shared",
        categories: ["seo", "accessibility"],
        score: 0,
        scoreDisplayMode: "binary",
        title: "Shared finding",
        description: "Needs work",
        displayValue: "failed",
        numericValue: 1,
        numericUnit: "item",
      },
    ]);
  });
});
