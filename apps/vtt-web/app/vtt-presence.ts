import {
  VTT_API_BASE_URL,
  VttApiError,
  type JsonValue,
} from "./vtt-client";
import { buildVttRequestHeaders } from "./vtt-transport";
import type { VttTableRole } from "./vtt-access";

export type PresenceStatus = "online" | "away" | "offline";

export interface PresenceRecord {
  schema_version: "vtt.presence_record.v1";
  participant_id: string;
  display_name: string;
  role: VttTableRole;
  status: PresenceStatus;
}

export interface PresenceView {
  schema_version: "vtt.presence_view.v1";
  table_id: string;
  revision: number;
  evaluated_at_ms: number;
  away_after_ms: number;
  offline_after_ms: number;
  records: PresenceRecord[];
}

export interface PresenceHeartbeatCommand {
  schema_version: "vtt.presence_command.v1";
  command_type: "heartbeat";
  table_id: string;
  command_id: string;
  expected_revision: number;
  participant_id: string;
  client_id: string;
}

export interface PresenceHeartbeatRequest {
  schema_version: "vtt.presence_heartbeat_request.v1";
  session_id: string;
  command: PresenceHeartbeatCommand;
}

export interface PresenceChangeSignal {
  schema_version: "vtt.presence_change_signal.v1";
  sequence: number;
  revision: number;
  participant_id: string;
}

export interface PresenceHeartbeatResponse {
  schema_version: "vtt.presence_heartbeat_response.v1";
  session_id: string;
  table_id: string;
  command_id: string;
  revision: number;
  replayed: boolean;
  signal: PresenceChangeSignal;
}

type ObjectValue = Record<string, unknown>;

function objectValue(value: unknown, path: string): ObjectValue {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`${path} must be an object`);
  }
  return value as ObjectValue;
}

function exactObject(
  value: unknown,
  keys: readonly string[],
  path: string,
): ObjectValue {
  const result = objectValue(value, path);
  const expected = new Set(keys);
  for (const key of Object.keys(result)) {
    if (!expected.has(key)) {
      throw new Error(`${path} contains unexpected field "${key}"`);
    }
  }
  for (const key of keys) {
    if (!(key in result)) throw new Error(`${path} is missing field "${key}"`);
  }
  return result;
}

function literalValue<T extends string>(
  value: unknown,
  allowed: readonly T[],
  path: string,
): T {
  if (typeof value !== "string" || !allowed.includes(value as T)) {
    throw new Error(`${path} must be one of ${allowed.join(", ")}`);
  }
  return value as T;
}

function canonicalText(
  value: unknown,
  path: string,
  maximumLength: number | null = 128,
): string {
  if (
    typeof value !== "string" ||
    value.length === 0 ||
    value.trim() !== value ||
    (maximumLength !== null && Array.from(value).length > maximumLength)
  ) {
    throw new Error(`${path} must be canonical non-empty text`);
  }
  return value;
}

function integerValue(value: unknown, path: string, minimum = 0): number {
  if (
    typeof value !== "number" ||
    !Number.isSafeInteger(value) ||
    value < minimum
  ) {
    throw new Error(`${path} must be a safe integer >= ${minimum}`);
  }
  return value;
}

function booleanValue(value: unknown, path: string): boolean {
  if (typeof value !== "boolean") throw new Error(`${path} must be a boolean`);
  return value;
}

function compareCodePoints(left: string, right: string): number {
  const leftPoints = Array.from(left, (character) => character.codePointAt(0) as number);
  const rightPoints = Array.from(right, (character) => character.codePointAt(0) as number);
  for (let index = 0; index < Math.min(leftPoints.length, rightPoints.length); index += 1) {
    if (leftPoints[index] !== rightPoints[index]) {
      return leftPoints[index] - rightPoints[index];
    }
  }
  return leftPoints.length - rightPoints.length;
}

function parsePresenceRecord(value: unknown, path: string): PresenceRecord {
  const data = exactObject(
    value,
    ["schema_version", "participant_id", "display_name", "role", "status"],
    path,
  );
  return {
    schema_version: literalValue(
      data.schema_version,
      ["vtt.presence_record.v1"],
      `${path}.schema_version`,
    ),
    participant_id: canonicalText(data.participant_id, `${path}.participant_id`, null),
    display_name: canonicalText(data.display_name, `${path}.display_name`, null),
    role: literalValue(data.role, ["gm", "player", "spectator"], `${path}.role`),
    status: literalValue(
      data.status,
      ["online", "away", "offline"],
      `${path}.status`,
    ),
  };
}

export function parsePresenceView(value: unknown): PresenceView {
  const data = exactObject(
    value,
    [
      "schema_version",
      "table_id",
      "revision",
      "evaluated_at_ms",
      "away_after_ms",
      "offline_after_ms",
      "records",
    ],
    "presence_view",
  );
  if (!Array.isArray(data.records)) {
    throw new Error("presence_view.records must be an ordered list");
  }
  const records = data.records.map((record, index) =>
    parsePresenceRecord(record, `presence_view.records[${index}]`),
  );
  const participantIds = records.map((record) => record.participant_id);
  if (new Set(participantIds).size !== participantIds.length) {
    throw new Error("presence_view.records must contain unique participant IDs");
  }
  if (
    participantIds.some(
      (participantId, index) =>
        index > 0 && compareCodePoints(participantIds[index - 1], participantId) > 0,
    )
  ) {
    throw new Error("presence_view.records must be sorted by participant ID");
  }
  const awayAfterMs = integerValue(data.away_after_ms, "presence_view.away_after_ms", 1);
  const offlineAfterMs = integerValue(
    data.offline_after_ms,
    "presence_view.offline_after_ms",
    1,
  );
  if (awayAfterMs >= offlineAfterMs) {
    throw new Error("presence_view.away_after_ms must be less than offline_after_ms");
  }
  return {
    schema_version: literalValue(
      data.schema_version,
      ["vtt.presence_view.v1"],
      "presence_view.schema_version",
    ),
    table_id: canonicalText(data.table_id, "presence_view.table_id"),
    revision: integerValue(data.revision, "presence_view.revision"),
    evaluated_at_ms: integerValue(
      data.evaluated_at_ms,
      "presence_view.evaluated_at_ms",
    ),
    away_after_ms: awayAfterMs,
    offline_after_ms: offlineAfterMs,
    records,
  };
}

export function assertPresenceViewMatchesTable(
  view: PresenceView,
  table: {
    table_id: string;
    participants: readonly {
      participant_id: string;
      display_name: string;
      role: VttTableRole;
    }[];
  },
): void {
  if (
    view.table_id !== table.table_id ||
    view.records.length !== table.participants.length ||
    view.records.some((record, index) => {
      const participant = table.participants[index];
      return (
        participant === undefined ||
        record.participant_id !== participant.participant_id ||
        record.display_name !== participant.display_name ||
        record.role !== participant.role
      );
    })
  ) {
    throw new Error("The presence directory does not match the authenticated table roster.");
  }
}

export function parsePresenceSignal(value: unknown): PresenceChangeSignal {
  const data = exactObject(
    value,
    ["schema_version", "sequence", "revision", "participant_id"],
    "presence_signal",
  );
  const sequence = integerValue(data.sequence, "presence_signal.sequence", 1);
  const revision = integerValue(data.revision, "presence_signal.revision", 1);
  if (sequence !== revision) {
    throw new Error("presence_signal sequence must match revision");
  }
  return {
    schema_version: literalValue(
      data.schema_version,
      ["vtt.presence_change_signal.v1"],
      "presence_signal.schema_version",
    ),
    sequence,
    revision,
    participant_id: canonicalText(
      data.participant_id,
      "presence_signal.participant_id",
    ),
  };
}

export function parsePresenceHeartbeatResponse(
  value: unknown,
): PresenceHeartbeatResponse {
  const data = exactObject(
    value,
    [
      "schema_version",
      "session_id",
      "table_id",
      "command_id",
      "revision",
      "replayed",
      "signal",
    ],
    "presence_response",
  );
  const revision = integerValue(data.revision, "presence_response.revision", 1);
  const signal = parsePresenceSignal(data.signal);
  if (signal.revision !== revision) {
    throw new Error("presence response signal revision must match response revision");
  }
  return {
    schema_version: literalValue(
      data.schema_version,
      ["vtt.presence_heartbeat_response.v1"],
      "presence_response.schema_version",
    ),
    session_id: canonicalText(data.session_id, "presence_response.session_id"),
    table_id: canonicalText(data.table_id, "presence_response.table_id"),
    command_id: canonicalText(data.command_id, "presence_response.command_id"),
    revision,
    replayed: booleanValue(data.replayed, "presence_response.replayed"),
    signal,
  };
}

export function buildPresenceHeartbeatRequest(input: {
  sessionId: string;
  tableId: string;
  expectedRevision: number;
  participantId: string;
  clientId: string;
  commandId?: string;
}): PresenceHeartbeatRequest {
  return {
    schema_version: "vtt.presence_heartbeat_request.v1",
    session_id: canonicalText(input.sessionId, "sessionId"),
    command: {
      schema_version: "vtt.presence_command.v1",
      command_type: "heartbeat",
      table_id: canonicalText(input.tableId, "tableId"),
      command_id: canonicalText(
        input.commandId ?? crypto.randomUUID(),
        "commandId",
      ),
      expected_revision: integerValue(input.expectedRevision, "expectedRevision"),
      participant_id: canonicalText(input.participantId, "participantId"),
      client_id: canonicalText(input.clientId, "clientId"),
    },
  };
}

export function presenceSignalForRequest(
  request: PresenceHeartbeatRequest,
  response: PresenceHeartbeatResponse,
): PresenceChangeSignal {
  if (
    response.session_id !== request.session_id ||
    response.table_id !== request.command.table_id ||
    response.command_id !== request.command.command_id ||
    response.signal.participant_id !== request.command.participant_id
  ) {
    throw new Error("The presence response does not match its request.");
  }
  return response.signal;
}

function jsonObject(value: unknown, path: string): Record<string, JsonValue> {
  return objectValue(value, path) as Record<string, JsonValue>;
}

async function presenceResponseJson(response: Response): Promise<unknown> {
  let value: unknown;
  try {
    value = await response.json();
  } catch {
    throw new VttApiError("The presence service returned unreadable data.", {
      code: "invalid_response",
      status: response.status,
    });
  }
  if (response.ok) return value;
  try {
    const error = exactObject(
      value,
      ["schema_version", "code", "message", "details"],
      "error",
    );
    literalValue(error.schema_version, ["vtt.error.v1"], "error.schema_version");
    throw new VttApiError(canonicalText(error.message, "error.message", 10_000), {
      code: canonicalText(error.code, "error.code"),
      status: response.status,
      details: jsonObject(error.details, "error.details"),
    });
  } catch (error) {
    if (error instanceof VttApiError) throw error;
    throw new VttApiError("The presence service rejected the request.", {
      code: "http_error",
      status: response.status,
    });
  }
}

export async function getPresenceView(
  signal?: AbortSignal,
  bearerToken?: string | null,
): Promise<PresenceView> {
  const response = await fetch(`${VTT_API_BASE_URL}/api/v1/presence`, {
    method: "GET",
    headers: buildVttRequestHeaders({
      accept: "application/json",
      bearerToken,
    }),
    signal,
  });
  return parsePresenceView(await presenceResponseJson(response));
}

export async function postPresenceHeartbeat(
  request: PresenceHeartbeatRequest,
  signal?: AbortSignal,
  bearerToken?: string | null,
): Promise<PresenceHeartbeatResponse> {
  const response = await fetch(`${VTT_API_BASE_URL}/api/v1/presence-heartbeats`, {
    method: "POST",
    headers: buildVttRequestHeaders({
      accept: "application/json",
      bearerToken,
      contentType: "application/json",
    }),
    body: JSON.stringify(request),
    signal,
  });
  return parsePresenceHeartbeatResponse(await presenceResponseJson(response));
}

export function presenceEventsUrl(after: number): string {
  if (!Number.isSafeInteger(after) || after < 0) {
    throw new Error(
      "Presence event cursor must be a non-negative integer within the safe range",
    );
  }
  return `${VTT_API_BASE_URL}/api/v1/presence-events?after=${after}`;
}

export function parsePresenceSseBlock(block: string): PresenceChangeSignal | null {
  if (typeof block !== "string") throw new Error("Presence SSE block must be text");
  const fields = new Map<string, string>();
  for (const rawLine of block.replaceAll("\r\n", "\n").split("\n")) {
    if (!rawLine || rawLine.startsWith(":")) continue;
    const separator = rawLine.indexOf(":");
    if (separator <= 0) throw new Error("Presence SSE contains a malformed field");
    const name = rawLine.slice(0, separator);
    const fieldValue = rawLine.slice(separator + 1).replace(/^ /, "");
    if (!new Set(["id", "event", "data"]).has(name) || fields.has(name)) {
      throw new Error("Presence SSE contains duplicate or unsupported fields");
    }
    fields.set(name, fieldValue);
  }
  if (fields.size === 0) return null;
  if (fields.get("event") !== "vtt.presence_changed") {
    throw new Error("Presence SSE event type is invalid");
  }
  const idText = fields.get("id");
  const dataText = fields.get("data");
  if (!idText || !dataText || !/^\d+$/.test(idText)) {
    throw new Error("Presence SSE id must be a canonical integer");
  }
  const id = Number(idText);
  if (!Number.isSafeInteger(id) || String(id) !== idText) {
    throw new Error("Presence SSE id must be a canonical safe integer");
  }
  let decoded: unknown;
  try {
    decoded = JSON.parse(dataText);
  } catch {
    throw new Error("Presence SSE data must be valid JSON");
  }
  const signal = parsePresenceSignal(decoded);
  if (id !== signal.sequence) {
    throw new Error("Presence SSE id must match the signal sequence");
  }
  return signal;
}

function findSseBoundary(buffer: string): { index: number; length: number } | null {
  const unix = buffer.indexOf("\n\n");
  const windows = buffer.indexOf("\r\n\r\n");
  if (unix < 0 && windows < 0) return null;
  if (windows >= 0 && (unix < 0 || windows < unix)) {
    return { index: windows, length: 4 };
  }
  return { index: unix, length: 2 };
}

export async function streamPresenceEvents(input: {
  after: number;
  bearerToken?: string | null;
  signal: AbortSignal;
  onSignal: (signal: PresenceChangeSignal) => void;
  onOpen?: () => void;
}): Promise<number> {
  let cursor = integerValue(input.after, "after");
  const response = await fetch(presenceEventsUrl(cursor), {
    method: "GET",
    headers: buildVttRequestHeaders({
      accept: "text/event-stream",
      bearerToken: input.bearerToken,
    }),
    signal: input.signal,
  });
  if (!response.ok) await presenceResponseJson(response);
  if (!response.body) {
    throw new VttApiError("The presence event stream has no response body.", {
      code: "invalid_response",
      status: response.status,
    });
  }
  input.onOpen?.();
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    let boundary = findSseBoundary(buffer);
    while (boundary !== null) {
      const signal = parsePresenceSseBlock(buffer.slice(0, boundary.index));
      buffer = buffer.slice(boundary.index + boundary.length);
      if (signal && signal.sequence > cursor) {
        cursor = signal.sequence;
        input.onSignal(signal);
      }
      boundary = findSseBoundary(buffer);
    }
    if (done) break;
  }
  if (buffer.trim() !== "") {
    throw new Error("Presence SSE ended with an incomplete event");
  }
  return cursor;
}
