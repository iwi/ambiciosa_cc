// Turn a strategy type's JSON Schema (from its Pydantic model) into form fields,
// and form values back into parameters. Adding a strategy type in Python needs
// no change here.

import type { JsonSchema } from "./types";

export type Field = {
  key: string;
  label: string;
  help: string;
  kind: "integer" | "number" | "choice" | "boolean" | "text";
  choices?: string[];
  optional: boolean; // may be left empty (the schema allows null)
  min?: number;
  max?: number;
  defaultValue: unknown;
};

export type FormValues = Record<string, string | boolean>;

function concrete(schema: JsonSchema): { schema: JsonSchema; optional: boolean } {
  if (schema.anyOf) {
    const nonNull = schema.anyOf.filter((s) => s.type !== "null");
    const optional = nonNull.length < schema.anyOf.length;
    return { schema: { ...schema, ...(nonNull[0] ?? {}), anyOf: undefined }, optional };
  }
  return { schema, optional: false };
}

export function fieldsFromSchema(schema: JsonSchema): Field[] {
  return Object.entries(schema.properties ?? {}).map(([key, raw]) => {
    const { schema: s, optional } = concrete(raw);
    const kind: Field["kind"] = s.enum
      ? "choice"
      : s.type === "integer"
        ? "integer"
        : s.type === "number"
          ? "number"
          : s.type === "boolean"
            ? "boolean"
            : "text";
    return {
      key,
      label: raw.title ?? key,
      help: raw.description ?? "",
      kind,
      choices: s.enum,
      optional,
      min: s.minimum,
      max: s.maximum,
      defaultValue: raw.default,
    };
  });
}

function toText(value: unknown): string {
  return value === null || value === undefined ? "" : String(value);
}

/** Form values for a set of fields, from existing parameters or the schema defaults. */
export function initialValues(fields: Field[], params?: Record<string, unknown>): FormValues {
  const values: FormValues = {};
  for (const f of fields) {
    const v = params && f.key in params ? params[f.key] : f.defaultValue;
    values[f.key] = f.kind === "boolean" ? Boolean(v) : toText(v);
  }
  return values;
}

export type Parsed = { params: Record<string, unknown>; errors: Record<string, string> };

/** Parameters from form values, with a message for each value that is not acceptable. */
export function parseValues(fields: Field[], values: FormValues): Parsed {
  const params: Record<string, unknown> = {};
  const errors: Record<string, string> = {};
  for (const f of fields) {
    const raw = values[f.key];
    if (f.kind === "boolean") {
      params[f.key] = Boolean(raw);
      continue;
    }
    const text = String(raw ?? "").trim();
    if (text === "") {
      if (f.optional) params[f.key] = null;
      else errors[f.key] = "Enter a value.";
      continue;
    }
    if (f.kind === "choice") {
      if (!f.choices?.includes(text)) errors[f.key] = `Choose one of ${f.choices?.join(", ")}.`;
      else params[f.key] = text;
      continue;
    }
    if (f.kind === "integer" || f.kind === "number") {
      const n = Number(text);
      if (!Number.isFinite(n)) {
        errors[f.key] = "Enter a number.";
      } else if (f.kind === "integer" && !Number.isInteger(n)) {
        errors[f.key] = "Enter a whole number.";
      } else if (f.min !== undefined && n < f.min) {
        errors[f.key] = `Must be at least ${f.min}.`;
      } else if (f.max !== undefined && n > f.max) {
        errors[f.key] = `Must be at most ${f.max}.`;
      } else {
        params[f.key] = n;
      }
      continue;
    }
    params[f.key] = text;
  }
  return { params, errors };
}

/** A short description of a strategy's parameters, e.g. "Bank at 30". */
export function describeParams(fields: Field[], params: Record<string, unknown>): string {
  return fields
    .map((f) => {
      const v = params[f.key];
      return `${f.label} ${v === null || v === undefined ? "none" : String(v)}`;
    })
    .join(", ");
}
