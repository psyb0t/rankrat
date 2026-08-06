import type lighthouse from "lighthouse";

import {
  MAX_DESCRIPTION_CHARS,
  MAX_DISPLAY_VALUE_CHARS,
  MAX_FINDINGS,
  MAX_ID_CHARS,
  MAX_TITLE_CHARS,
  type LighthouseCategory,
} from "./constants.js";
import { auditReportSchema, type AuditReport } from "./schemas.js";

const EXCLUDED_SCORE_MODES = new Set([
  "notApplicable",
  "manual",
  "informative",
]);

export type LighthouseRunResult = NonNullable<
  Awaited<ReturnType<typeof lighthouse>>
>;

function bounded(value: string | undefined, maximum: number): string {
  return (value ?? "").slice(0, maximum);
}

export function reportFromResult(
  result: LighthouseRunResult,
  requestedCategories: LighthouseCategory[],
): AuditReport {
  const lhr = result.lhr;
  const categories = Object.fromEntries(
    requestedCategories.map((category) => [
      category,
      { score: lhr.categories[category]?.score ?? null },
    ]),
  );
  const categoriesByAudit = new Map<string, LighthouseCategory[]>();
  for (const category of requestedCategories) {
    for (const reference of lhr.categories[category]?.auditRefs ?? []) {
      const current = categoriesByAudit.get(reference.id) ?? [];
      if (!current.includes(category)) {
        current.push(category);
      }
      categoriesByAudit.set(reference.id, current);
    }
  }
  const findings = [...categoriesByAudit.entries()]
    .flatMap(([id, findingCategories]) => {
      const audit = lhr.audits[id];
      if (
        audit === undefined ||
        EXCLUDED_SCORE_MODES.has(audit.scoreDisplayMode) ||
        (audit.score !== null && audit.score >= 1)
      ) {
        return [];
      }
      return [
        {
          id: bounded(audit.id, MAX_ID_CHARS),
          categories: findingCategories,
          score: audit.score,
          scoreDisplayMode: bounded(audit.scoreDisplayMode, MAX_ID_CHARS),
          title: bounded(audit.title, MAX_TITLE_CHARS),
          description: bounded(audit.description, MAX_DESCRIPTION_CHARS),
          ...(audit.displayValue === undefined
            ? {}
            : {
                displayValue: bounded(
                  audit.displayValue,
                  MAX_DISPLAY_VALUE_CHARS,
                ),
              }),
          ...(audit.numericValue === undefined
            ? {}
            : { numericValue: audit.numericValue }),
          ...(audit.numericUnit === undefined
            ? {}
            : { numericUnit: bounded(audit.numericUnit, MAX_ID_CHARS) }),
        },
      ];
    })
    .sort((left, right) => left.id.localeCompare(right.id))
    .slice(0, MAX_FINDINGS);
  return auditReportSchema.parse({
    requestedUrl: lhr.requestedUrl,
    finalUrl: lhr.mainDocumentUrl ?? lhr.finalDisplayedUrl,
    fetchTime: lhr.fetchTime,
    lighthouseVersion: lhr.lighthouseVersion,
    categories,
    findings,
  });
}
