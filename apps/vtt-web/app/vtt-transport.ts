export const MINIMUM_VTT_BEARER_TOKEN_LENGTH = 16;

export function normalizeVttBearerToken(
  value: string | null | undefined,
): string | null {
  if (value === null || value === undefined) return null;
  if (typeof value !== "string") {
    throw new TypeError("The table credential must be text.");
  }
  if (value !== value.trim() || /\s/u.test(value)) {
    throw new Error("The table credential must not contain whitespace.");
  }
  if (value.length < MINIMUM_VTT_BEARER_TOKEN_LENGTH) {
    throw new Error(
      `The table credential must contain at least ${MINIMUM_VTT_BEARER_TOKEN_LENGTH} characters.`,
    );
  }
  if (!/^[\x21-\x7e]+$/u.test(value)) {
    throw new Error("The table credential must contain only printable ASCII characters.");
  }
  return value;
}

export function buildVttRequestHeaders(input: {
  accept: "application/json" | "text/event-stream";
  bearerToken?: string | null;
  contentType?: "application/json";
}): Record<string, string> {
  const headers: Record<string, string> = { accept: input.accept };
  if (input.contentType !== undefined) {
    headers["content-type"] = input.contentType;
  }
  const bearerToken = normalizeVttBearerToken(input.bearerToken);
  if (bearerToken !== null) {
    headers.authorization = `Bearer ${bearerToken}`;
  }
  return headers;
}
