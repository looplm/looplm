export function getApiBase(): string {
  const envBase = process.env.NEXT_PUBLIC_API_URL;
  if (envBase && envBase.trim()) {
    return envBase.replace(/\/$/, "");
  }

  // Use relative URLs so the Next.js rewrite proxy handles forwarding
  return "";
}

export function buildApiUrl(
  path: string,
  params?: Record<string, string>
): string {
  const base = getApiBase();
  const qs = params ? new URLSearchParams(params).toString() : "";
  return `${base}${path}${qs ? `?${qs}` : ""}`;
}
