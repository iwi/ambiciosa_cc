import { describe, expect, it } from "vitest";
import { describeParams, fieldsFromSchema, initialValues, parseValues } from "./schemaForm";
import type { JsonSchema } from "./types";

// Schemas exactly as the API serves them (Pydantic's model_json_schema()).
const combined: JsonSchema = {
  properties: {
    threshold: { default: 50, description: "Points condition", minimum: 1, title: "Points to bank", type: "integer" },
    max_throws: { default: 4, description: "Throws condition", minimum: 1, title: "Throws to bank", type: "integer" },
    logic: { default: "or", description: "or / and", enum: ["or", "and"], title: "Combine conditions with", type: "string" },
  },
};
const random: JsonSchema = {
  properties: { p_continue: { default: 0.75, maximum: 1, minimum: 0, title: "Chance of continuing", type: "number" } },
};
const gameState: JsonSchema = {
  properties: {
    leading_threshold: { default: 30, minimum: 1, title: "When ahead, bank at", type: "integer" },
    close_threshold: {
      anyOf: [{ minimum: 1, type: "integer" }, { type: "null" }],
      default: null,
      title: "When close to winning, bank at",
    },
  },
};

describe("fieldsFromSchema", () => {
  it("maps types, titles, limits and choices", () => {
    const f = fieldsFromSchema(combined);
    expect(f.map((x) => [x.key, x.kind, x.label])).toEqual([
      ["threshold", "integer", "Points to bank"],
      ["max_throws", "integer", "Throws to bank"],
      ["logic", "choice", "Combine conditions with"],
    ]);
    expect(f[0].min).toBe(1);
    expect(f[2].choices).toEqual(["or", "and"]);
  });

  it("treats a nullable field as optional and keeps its limits", () => {
    const [, close] = fieldsFromSchema(gameState);
    expect(close).toMatchObject({ kind: "integer", optional: true, min: 1, defaultValue: null });
  });

  it("reads number bounds", () => {
    expect(fieldsFromSchema(random)[0]).toMatchObject({ kind: "number", min: 0, max: 1 });
  });
});

describe("initialValues", () => {
  it("uses defaults, or existing parameters when editing", () => {
    const f = fieldsFromSchema(gameState);
    expect(initialValues(f)).toEqual({ leading_threshold: "30", close_threshold: "" });
    expect(initialValues(f, { leading_threshold: 40, close_threshold: 80 })).toEqual({
      leading_threshold: "40",
      close_threshold: "80",
    });
  });
});

describe("parseValues", () => {
  it("returns typed parameters for valid input", () => {
    const f = fieldsFromSchema(combined);
    expect(parseValues(f, { threshold: " 60 ", max_throws: "3", logic: "and" })).toEqual({
      params: { threshold: 60, max_throws: 3, logic: "and" },
      errors: {},
    });
  });

  it("turns an empty optional field into null", () => {
    const f = fieldsFromSchema(gameState);
    expect(parseValues(f, { leading_threshold: "30", close_threshold: "" }).params.close_threshold).toBeNull();
  });

  it("explains each unacceptable value", () => {
    const f = fieldsFromSchema(combined);
    const { errors } = parseValues(f, { threshold: "", max_throws: "2.5", logic: "xor" });
    expect(errors).toEqual({
      threshold: "Enter a value.",
      max_throws: "Enter a whole number.",
      logic: "Choose one of or, and.",
    });
    const r = fieldsFromSchema(random);
    expect(parseValues(r, { p_continue: "1.5" }).errors.p_continue).toBe("Must be at most 1.");
    expect(parseValues(r, { p_continue: "-0.1" }).errors.p_continue).toBe("Must be at least 0.");
    expect(parseValues(r, { p_continue: "abc" }).errors.p_continue).toBe("Enter a number.");
    expect(parseValues(fieldsFromSchema(gameState), { leading_threshold: "0", close_threshold: "" }).errors)
      .toEqual({ leading_threshold: "Must be at least 1." });
  });
});

describe("describeParams", () => {
  it("summarises parameters with their labels", () => {
    expect(describeParams(fieldsFromSchema(gameState), { leading_threshold: 30, close_threshold: null })).toBe(
      "When ahead, bank at 30, When close to winning, bank at none",
    );
  });
});
