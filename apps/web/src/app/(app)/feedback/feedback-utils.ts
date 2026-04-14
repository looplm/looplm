export function extractUserQuestion(input: unknown, maxLen?: number): string {
  const limit = maxLen ?? 0; // 0 = no limit
  function truncate(s: string) {
    return limit > 0 && s.length > limit ? s.slice(0, limit) + "\u2026" : s;
  }
  if (!input) return "\u2014";
  if (typeof input === "string") return truncate(input);
  if (Array.isArray(input)) {
    const last = input.filter((m: any) => m.role === "user").pop();
    if (last?.content) {
      const text = typeof last.content === "string" ? last.content : JSON.stringify(last.content);
      return truncate(text);
    }
  }
  if (typeof input === "object" && input !== null) {
    const obj = input as Record<string, unknown>;
    if (obj.messages && Array.isArray(obj.messages)) {
      return extractUserQuestion(obj.messages, maxLen);
    }
    const text = JSON.stringify(input);
    return truncate(text);
  }
  return "\u2014";
}

export function extractAiResponse(output: unknown): string {
  if (!output) return "\u2014";
  if (typeof output === "string") return output;
  if (typeof output === "object" && output !== null) {
    const obj = output as Record<string, unknown>;
    // Common patterns: { text: "..." }, { content: "..." }, { answer: "..." }
    if (typeof obj.text === "string") return obj.text;
    if (typeof obj.content === "string") return obj.content;
    if (typeof obj.answer === "string") return obj.answer;
    // Array of messages — take last assistant message
    if (Array.isArray(output)) {
      const last = output.filter((m: any) => m.role === "assistant").pop();
      if (last?.content) return typeof last.content === "string" ? last.content : JSON.stringify(last.content);
    }
    if (obj.messages && Array.isArray(obj.messages)) {
      return extractAiResponse(obj.messages);
    }
    return JSON.stringify(output, null, 2);
  }
  return String(output);
}
