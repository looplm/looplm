export interface EvaluatorFormData {
  name: string;
  display_name: string;
  type: string;
  source: string;
  description: string;
  relevance: string;
  affects_pass: boolean;
  config: string;
}

export const EMPTY_FORM: EvaluatorFormData = {
  name: "",
  display_name: "",
  type: "llm_judge",
  source: "custom",
  description: "",
  relevance: "important",
  affects_pass: false,
  config: "{}",
};

export interface StructuredConfig {
  prompt_template: string;
  model: string;
  check_type: string;
  pattern: string;
  expected_strings: string;
}

export const EMPTY_STRUCTURED: StructuredConfig = {
  prompt_template: "",
  model: "",
  check_type: "contains_urls",
  pattern: "",
  expected_strings: "",
};

export function parseStructuredConfig(configObj: Record<string, unknown>): StructuredConfig {
  return {
    prompt_template: typeof configObj.prompt_template === "string" ? configObj.prompt_template : "",
    model: typeof configObj.model === "string" ? configObj.model : "",
    check_type: typeof configObj.check_type === "string" ? configObj.check_type : "contains_urls",
    pattern: typeof configObj.pattern === "string" ? configObj.pattern : "",
    expected_strings: Array.isArray(configObj.expected_strings)
      ? configObj.expected_strings.join("\n")
      : typeof configObj.expected_strings === "string"
        ? configObj.expected_strings
        : "",
  };
}

export function mergeStructuredIntoRaw(raw: string, structured: StructuredConfig, type: string): string {
  let base: Record<string, unknown> = {};
  try {
    base = JSON.parse(raw);
  } catch {
    // ignore parse errors, start fresh
  }

  if (type === "llm_judge" || type === "hybrid") {
    if (structured.prompt_template) base.prompt_template = structured.prompt_template;
    else delete base.prompt_template;
    if (structured.model) base.model = structured.model;
    else delete base.model;
  }

  if (type === "deterministic" || type === "hybrid") {
    base.check_type = structured.check_type;
    if (structured.check_type === "regex_match") {
      base.pattern = structured.pattern;
      delete base.expected_strings;
    } else if (structured.check_type === "string_contains") {
      base.expected_strings = structured.expected_strings
        .split("\n")
        .map((s) => s.trim())
        .filter(Boolean);
      delete base.pattern;
    } else {
      delete base.pattern;
      delete base.expected_strings;
    }
  }

  // Clean fields not relevant to current type
  if (type === "llm_judge") {
    delete base.check_type;
    delete base.pattern;
    delete base.expected_strings;
  }
  if (type === "deterministic") {
    delete base.prompt_template;
    delete base.model;
  }

  return JSON.stringify(base, null, 2);
}
