import { z } from "zod";

import {
  LIGHTHOUSE_CATEGORIES,
  MAX_DESCRIPTION_CHARS,
  MAX_DISPLAY_VALUE_CHARS,
  MAX_FINDINGS,
  MAX_ID_CHARS,
  MAX_TITLE_CHARS,
} from "./constants.js";

const safeHttpsUrlSchema = z.url({ protocol: /^https$/ }).refine((value) => {
  const url = new URL(value);
  return (
    url.username === "" &&
    url.password === "" &&
    (url.port === "" || url.port === "443") &&
    url.hash === ""
  );
}, "URL must use HTTPS without credentials, fragments, or a nonstandard port");

export const auditRequestSchema = z
  .object({
    url: safeHttpsUrlSchema,
    categories: z
      .array(z.enum(LIGHTHOUSE_CATEGORIES))
      .min(1)
      .max(LIGHTHOUSE_CATEGORIES.length),
  })
  .strict()
  .superRefine((value, context) => {
    if (new Set(value.categories).size !== value.categories.length) {
      context.addIssue({
        code: "custom",
        message: "categories must not repeat",
      });
    }
  });

export type AuditRequest = z.infer<typeof auditRequestSchema>;

const findingSchema = z
  .object({
    id: z.string().min(1).max(MAX_ID_CHARS),
    categories: z
      .array(z.enum(LIGHTHOUSE_CATEGORIES))
      .min(1)
      .max(LIGHTHOUSE_CATEGORIES.length),
    score: z.number().min(0).max(1).nullable(),
    scoreDisplayMode: z.string().min(1).max(MAX_ID_CHARS),
    title: z.string().min(1).max(MAX_TITLE_CHARS),
    description: z.string().max(MAX_DESCRIPTION_CHARS),
    displayValue: z.string().max(MAX_DISPLAY_VALUE_CHARS).optional(),
    numericValue: z.number().optional(),
    numericUnit: z.string().min(1).max(MAX_ID_CHARS).optional(),
  })
  .strict()
  .superRefine((value, context) => {
    if (new Set(value.categories).size !== value.categories.length) {
      context.addIssue({
        code: "custom",
        message: "finding categories must not repeat",
      });
    }
  });

export const auditReportSchema = z
  .object({
    requestedUrl: safeHttpsUrlSchema,
    finalUrl: safeHttpsUrlSchema,
    fetchTime: z.iso.datetime({ offset: true }),
    lighthouseVersion: z.string().min(1).max(MAX_ID_CHARS),
    categories: z
      .partialRecord(
        z.enum(LIGHTHOUSE_CATEGORIES),
        z.object({ score: z.number().min(0).max(1).nullable() }).strict(),
      )
      .refine(
        (value) => Object.keys(value).length > 0,
        "at least one category is required",
      ),
    findings: z.array(findingSchema).max(MAX_FINDINGS),
  })
  .strict();

export type AuditReport = z.infer<typeof auditReportSchema>;
