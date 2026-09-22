import { VTT_API_BASE_URL, VttApiError, type JsonValue } from "./vtt-client";
import { buildVttRequestHeaders } from "./vtt-transport";
import type { AxialHexCell } from "./vtt-board-calibration";

export interface TokenPose {
  schema_version: "vtt.token_pose.v1";
  position_ft: { x_ft: number; y_ft: number; z_ft: number };
  width_ft: number;
  height_ft: number;
  rotation_degrees: number;
  layer: number;
  occupied_hex_cells?: AxialHexCell[];
}

export interface TokenRecord {
  schema_version: "vtt.token_record.v1";
  token_id: string;
  scene_id: string;
  actor_id: string | null;
  name: string;
  pose: TokenPose;
  visibility: "public" | "owners" | "gm_only";
  locked: boolean;
  nameplate: "hidden" | "hover" | "always";
  show_hp_bar: boolean;
  aura_radius_ft: number;
  aura_color: string;
  condition_labels: string[];
}

export interface TokenView {
  schema_version: "vtt.token_view.v1";
  table_id: string;
  scene_id: string;
  revision: number;
  tokens: TokenRecord[];
}

interface TokenCommandBase {
  schema_version: "vtt.token_command.v1";
  table_id: string;
  command_id: string;
  expected_revision: number;
}

export interface TokenCreateCommand extends TokenCommandBase {
  command_type: "create";
  token: TokenRecord;
}

export interface TokenUpdateCommand extends TokenCommandBase {
  command_type: "update";
  token: TokenRecord;
}

export interface TokenDuplicateCommand extends TokenCommandBase {
  command_type: "duplicate";
  source_token_id: string;
  new_token_id: string;
  pose: TokenPose;
}

export interface TokenDeleteCommand extends TokenCommandBase {
  command_type: "delete";
  scene_id: string;
  token_id: string;
}

export type TokenCommand =
  | TokenCreateCommand
  | TokenUpdateCommand
  | TokenDuplicateCommand
  | TokenDeleteCommand;

export interface TokenRequest {
  schema_version: "vtt.token_request.v1";
  session_id: string;
  command: TokenCommand;
}

export interface TokenResponse {
  schema_version: "vtt.token_response.v1";
  session_id: string;
  table_id: string;
  command_id: string;
  revision: number;
  replayed: boolean;
  event: Record<string, unknown>;
}

export interface TokenChangeSignal {
  schema_version: "vtt.token_change_signal.v1";
  sequence: number;
  revision: number;
  scene_id: string;
}

type ObjectValue = Record<string, unknown>;

function objectValue(value: unknown, path: string): ObjectValue {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`${path} must be an object`);
  }
  return value as ObjectValue;
}

function exactObject(value: unknown, keys: readonly string[], path: string): ObjectValue {
  const result = objectValue(value, path);
  const expected = new Set(keys);
  for (const key of Object.keys(result)) {
    if (!expected.has(key)) throw new Error(`${path} contains unexpected field "${key}"`);
  }
  for (const key of keys) {
    if (!(key in result)) throw new Error(`${path} is missing field "${key}"`);
  }
  return result;
}

function canonicalText(value: unknown, path: string, maximum = 160): string {
  if (
    typeof value !== "string" ||
    value.length === 0 ||
    value.trim() !== value ||
    value.length > maximum
  ) {
    throw new Error(`${path} must be canonical non-empty text`);
  }
  return value;
}

function literal<T extends string>(value: unknown, values: readonly T[], path: string): T {
  if (typeof value !== "string" || !values.includes(value as T)) {
    throw new Error(`${path} has an unsupported value`);
  }
  return value as T;
}

function finite(value: unknown, path: string, minimum?: number, maximum?: number): number {
  if (
    typeof value !== "number" ||
    !Number.isFinite(value) ||
    (minimum !== undefined && value < minimum) ||
    (maximum !== undefined && value > maximum)
  ) {
    throw new Error(`${path} must be a bounded finite number`);
  }
  return value;
}

function integer(value: unknown, path: string, minimum = 0, maximum = Number.MAX_SAFE_INTEGER): number {
  if (!Number.isSafeInteger(value) || (value as number) < minimum || (value as number) > maximum) {
    throw new Error(`${path} must be a bounded safe integer`);
  }
  return value as number;
}

function booleanValue(value: unknown, path: string): boolean {
  if (typeof value !== "boolean") throw new Error(`${path} must be a boolean`);
  return value;
}

function compareCodePoints(left: string, right: string): number {
  const a = Array.from(left, (value) => value.codePointAt(0) as number);
  const b = Array.from(right, (value) => value.codePointAt(0) as number);
  for (let index = 0; index < Math.min(a.length, b.length); index += 1) {
    if (a[index] !== b[index]) return a[index] - b[index];
  }
  return a.length - b.length;
}

function parsePose(value: unknown, path: string): TokenPose {
  const input = objectValue(value, path);
  const data = exactObject(
    value,
    [
      "schema_version",
      "position_ft",
      "width_ft",
      "height_ft",
      "rotation_degrees",
      "layer",
      ...("occupied_hex_cells" in input
        ? ["occupied_hex_cells"]
        : []),
    ],
    path,
  );
  const position = exactObject(
    data.position_ft,
    ["x_ft", "y_ft", "z_ft"],
    `${path}.position_ft`,
  );
  const rotation = finite(data.rotation_degrees, `${path}.rotation_degrees`, 0);
  if (rotation >= 360) throw new Error(`${path}.rotation_degrees must be below 360`);
  let occupiedHexCells: AxialHexCell[] | undefined;
  if (data.occupied_hex_cells !== undefined) {
    if (!Array.isArray(data.occupied_hex_cells) || data.occupied_hex_cells.length > 64) {
      throw new Error(`${path}.occupied_hex_cells must be a bounded ordered list`);
    }
    occupiedHexCells = data.occupied_hex_cells.map((value, index) => {
      const cell = exactObject(
        value,
        ["q", "r"],
        `${path}.occupied_hex_cells[${index}]`,
      );
      return {
        q: integer(cell.q, `${path}.occupied_hex_cells[${index}].q`, -1_000_000, 1_000_000),
        r: integer(cell.r, `${path}.occupied_hex_cells[${index}].r`, -1_000_000, 1_000_000),
      };
    });
    for (let index = 0; index < occupiedHexCells.length; index += 1) {
      const previous = occupiedHexCells[index - 1];
      const current = occupiedHexCells[index];
      if (
        previous &&
        (previous.q > current.q ||
          (previous.q === current.q && previous.r >= current.r))
      ) {
        throw new Error(`${path}.occupied_hex_cells must be unique and sorted`);
      }
    }
  }
  return {
    schema_version: literal(
      data.schema_version,
      ["vtt.token_pose.v1"],
      `${path}.schema_version`,
    ),
    position_ft: {
      x_ft: finite(position.x_ft, `${path}.position_ft.x_ft`),
      y_ft: finite(position.y_ft, `${path}.position_ft.y_ft`),
      z_ft: finite(position.z_ft, `${path}.position_ft.z_ft`),
    },
    width_ft: finite(data.width_ft, `${path}.width_ft`, Number.MIN_VALUE, 500),
    height_ft: finite(data.height_ft, `${path}.height_ft`, Number.MIN_VALUE, 500),
    rotation_degrees: rotation,
    layer: integer(data.layer, `${path}.layer`, -100, 100),
    ...(occupiedHexCells === undefined
      ? {}
      : { occupied_hex_cells: occupiedHexCells }),
  };
}

export function parseTokenRecord(value: unknown, path = "token"): TokenRecord {
  const data = exactObject(
    value,
    [
      "schema_version",
      "token_id",
      "scene_id",
      "actor_id",
      "name",
      "pose",
      "visibility",
      "locked",
      "nameplate",
      "show_hp_bar",
      "aura_radius_ft",
      "aura_color",
      "condition_labels",
    ],
    path,
  );
  const tokenId = canonicalText(data.token_id, `${path}.token_id`, 128);
  if (!/^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/.test(tokenId)) {
    throw new Error(`${path}.token_id must be URL-safe`);
  }
  const actorId =
    data.actor_id === null ? null : canonicalText(data.actor_id, `${path}.actor_id`, 128);
  const visibility = literal(
    data.visibility,
    ["public", "owners", "gm_only"],
    `${path}.visibility`,
  );
  if (visibility === "owners" && actorId === null) {
    throw new Error(`${path}.owners visibility requires an actor link`);
  }
  if (!Array.isArray(data.condition_labels)) {
    throw new Error(`${path}.condition_labels must be an ordered list`);
  }
  const conditions = data.condition_labels.map((condition, index) =>
    canonicalText(condition, `${path}.condition_labels[${index}]`, 80),
  );
  if (
    conditions.length > 32 ||
    new Set(conditions).size !== conditions.length ||
    conditions.some(
      (condition, index) => index > 0 && compareCodePoints(conditions[index - 1], condition) > 0,
    )
  ) {
    throw new Error(`${path}.condition_labels must be unique and sorted`);
  }
  const auraColor = canonicalText(data.aura_color, `${path}.aura_color`, 7);
  if (!/^#[0-9A-F]{6}$/.test(auraColor)) {
    throw new Error(`${path}.aura_color must be an uppercase hex color`);
  }
  return {
    schema_version: literal(
      data.schema_version,
      ["vtt.token_record.v1"],
      `${path}.schema_version`,
    ),
    token_id: tokenId,
    scene_id: canonicalText(data.scene_id, `${path}.scene_id`, 128),
    actor_id: actorId,
    name: canonicalText(data.name, `${path}.name`),
    pose: parsePose(data.pose, `${path}.pose`),
    visibility,
    locked: booleanValue(data.locked, `${path}.locked`),
    nameplate: literal(
      data.nameplate,
      ["hidden", "hover", "always"],
      `${path}.nameplate`,
    ),
    show_hp_bar: booleanValue(data.show_hp_bar, `${path}.show_hp_bar`),
    aura_radius_ft: finite(data.aura_radius_ft, `${path}.aura_radius_ft`, 0, 1_000),
    aura_color: auraColor,
    condition_labels: conditions,
  };
}

export function parseTokenView(value: unknown): TokenView {
  const data = exactObject(
    value,
    ["schema_version", "table_id", "scene_id", "revision", "tokens"],
    "token_view",
  );
  if (!Array.isArray(data.tokens)) throw new Error("token_view.tokens must be an ordered list");
  const sceneId = canonicalText(data.scene_id, "token_view.scene_id", 128);
  const tokens = data.tokens.map((token, index) =>
    parseTokenRecord(token, `token_view.tokens[${index}]`),
  );
  const ids = tokens.map((token) => token.token_id);
  if (
    new Set(ids).size !== ids.length ||
    ids.some((id, index) => index > 0 && compareCodePoints(ids[index - 1], id) > 0) ||
    tokens.some((token) => token.scene_id !== sceneId)
  ) {
    throw new Error("token_view tokens must be unique, sorted, and scene-bound");
  }
  return {
    schema_version: literal(
      data.schema_version,
      ["vtt.token_view.v1"],
      "token_view.schema_version",
    ),
    table_id: canonicalText(data.table_id, "token_view.table_id", 128),
    scene_id: sceneId,
    revision: integer(data.revision, "token_view.revision"),
    tokens,
  };
}

function commandBase(input: {
  tableId: string;
  commandId?: string;
  expectedRevision: number;
}): TokenCommandBase {
  return {
    schema_version: "vtt.token_command.v1",
    table_id: canonicalText(input.tableId, "tableId", 128),
    command_id: canonicalText(input.commandId ?? crypto.randomUUID(), "commandId", 128),
    expected_revision: integer(input.expectedRevision, "expectedRevision"),
  };
}

function request(sessionId: string, command: TokenCommand): TokenRequest {
  return {
    schema_version: "vtt.token_request.v1",
    session_id: canonicalText(sessionId, "sessionId", 128),
    command,
  };
}

export function buildTokenCreateRequest(input: {
  sessionId: string;
  tableId: string;
  commandId?: string;
  expectedRevision: number;
  token: TokenRecord;
}): TokenRequest {
  return request(input.sessionId, {
    ...commandBase(input),
    command_type: "create",
    token: parseTokenRecord(input.token),
  });
}

export function buildTokenUpdateRequest(input: {
  sessionId: string;
  tableId: string;
  commandId?: string;
  expectedRevision: number;
  token: TokenRecord;
}): TokenRequest {
  return request(input.sessionId, {
    ...commandBase(input),
    command_type: "update",
    token: parseTokenRecord(input.token),
  });
}

export function buildTokenDuplicateRequest(input: {
  sessionId: string;
  tableId: string;
  commandId?: string;
  expectedRevision: number;
  sourceTokenId: string;
  newTokenId: string;
  pose: TokenPose;
}): TokenRequest {
  return request(input.sessionId, {
    ...commandBase(input),
    command_type: "duplicate",
    source_token_id: canonicalText(input.sourceTokenId, "sourceTokenId", 128),
    new_token_id: canonicalText(input.newTokenId, "newTokenId", 128),
    pose: parsePose(input.pose, "pose"),
  });
}

export function buildTokenDeleteRequest(input: {
  sessionId: string;
  tableId: string;
  commandId?: string;
  expectedRevision: number;
  sceneId: string;
  tokenId: string;
}): TokenRequest {
  return request(input.sessionId, {
    ...commandBase(input),
    command_type: "delete",
    scene_id: canonicalText(input.sceneId, "sceneId", 128),
    token_id: canonicalText(input.tokenId, "tokenId", 128),
  });
}

async function responseJson(response: Response): Promise<unknown> {
  let value: unknown;
  try {
    value = await response.json();
  } catch {
    throw new VttApiError("The token service returned unreadable data.", {
      code: "invalid_response",
      status: response.status,
    });
  }
  if (response.ok) return value;
  try {
    const data = exactObject(
      value,
      ["schema_version", "code", "message", "details"],
      "error",
    );
    literal(data.schema_version, ["vtt.error.v1"], "error.schema_version");
    throw new VttApiError(canonicalText(data.message, "error.message", 10_000), {
      code: canonicalText(data.code, "error.code", 128),
      status: response.status,
      details: objectValue(data.details, "error.details") as Record<string, JsonValue>,
    });
  } catch (error) {
    if (error instanceof VttApiError) throw error;
    throw new VttApiError("The token service rejected the request.", {
      code: "http_error",
      status: response.status,
    });
  }
}

export async function getTokenView(
  sceneId: string,
  signal?: AbortSignal,
  bearerToken?: string | null,
): Promise<TokenView> {
  const query = new URLSearchParams({ scene_id: canonicalText(sceneId, "sceneId", 128) });
  const response = await fetch(`${VTT_API_BASE_URL}/api/v1/tokens?${query}`, {
    method: "GET",
    headers: buildVttRequestHeaders({ accept: "application/json", bearerToken }),
    signal,
  });
  return parseTokenView(await responseJson(response));
}

export async function postTokenRequest(
  payload: TokenRequest,
  signal?: AbortSignal,
  bearerToken?: string | null,
): Promise<TokenResponse> {
  const response = await fetch(`${VTT_API_BASE_URL}/api/v1/token-commands`, {
    method: "POST",
    headers: buildVttRequestHeaders({
      accept: "application/json",
      contentType: "application/json",
      bearerToken,
    }),
    body: JSON.stringify(payload),
    signal,
  });
  const value = await responseJson(response);
  const data = exactObject(
    value,
    ["schema_version", "session_id", "table_id", "command_id", "revision", "replayed", "event"],
    "token_response",
  );
  return {
    schema_version: literal(
      data.schema_version,
      ["vtt.token_response.v1"],
      "token_response.schema_version",
    ),
    session_id: canonicalText(data.session_id, "token_response.session_id", 128),
    table_id: canonicalText(data.table_id, "token_response.table_id", 128),
    command_id: canonicalText(data.command_id, "token_response.command_id", 128),
    revision: integer(data.revision, "token_response.revision", 1),
    replayed: booleanValue(data.replayed, "token_response.replayed"),
    event: objectValue(data.event, "token_response.event"),
  };
}

export function parseTokenChangeSignal(value: unknown): TokenChangeSignal {
  const data = exactObject(
    value,
    ["schema_version", "sequence", "revision", "scene_id"],
    "token_change_signal",
  );
  const sequence = integer(data.sequence, "token_change_signal.sequence", 1);
  const revision = integer(data.revision, "token_change_signal.revision", 1);
  if (sequence !== revision) {
    throw new Error("token_change_signal sequence must match revision");
  }
  return {
    schema_version: literal(
      data.schema_version,
      ["vtt.token_change_signal.v1"],
      "token_change_signal.schema_version",
    ),
    sequence,
    revision,
    scene_id: canonicalText(data.scene_id, "token_change_signal.scene_id", 128),
  };
}

export function tokenEventsUrl(sceneId: string, after: number): string {
  const query = new URLSearchParams({
    scene_id: canonicalText(sceneId, "sceneId", 128),
    after: String(integer(after, "after")),
  });
  return `${VTT_API_BASE_URL}/api/v1/token-events?${query}`;
}

export function parseTokenSseBlock(block: string): TokenChangeSignal | null {
  if (typeof block !== "string") throw new Error("Token SSE block must be text");
  const fields = new Map<string, string>();
  for (const rawLine of block.replaceAll("\r\n", "\n").split("\n")) {
    if (!rawLine || rawLine.startsWith(":")) continue;
    const separator = rawLine.indexOf(":");
    if (separator <= 0) throw new Error("Token SSE contains a malformed field");
    const name = rawLine.slice(0, separator);
    const fieldValue = rawLine.slice(separator + 1).replace(/^ /, "");
    if (!["id", "event", "data"].includes(name) || fields.has(name)) {
      throw new Error("Token SSE contains duplicate or unsupported fields");
    }
    fields.set(name, fieldValue);
  }
  if (fields.size === 0) return null;
  if (fields.get("event") !== "vtt.tokens_changed") {
    throw new Error("Token SSE event type is invalid");
  }
  const idText = fields.get("id");
  const dataText = fields.get("data");
  if (!idText || !dataText || !/^\d+$/.test(idText)) {
    throw new Error("Token SSE id must be a canonical integer");
  }
  const id = Number(idText);
  if (!Number.isSafeInteger(id) || String(id) !== idText) {
    throw new Error("Token SSE id must be a canonical safe integer");
  }
  let decoded: unknown;
  try {
    decoded = JSON.parse(dataText);
  } catch {
    throw new Error("Token SSE data must be valid JSON");
  }
  const signal = parseTokenChangeSignal(decoded);
  if (signal.sequence !== id) throw new Error("Token SSE id must match sequence");
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

export async function streamTokenEvents(input: {
  sceneId: string;
  after: number;
  bearerToken?: string | null;
  signal: AbortSignal;
  onEvent: (event: TokenChangeSignal) => void;
  onOpen?: () => void;
}): Promise<number> {
  let cursor = integer(input.after, "after");
  const response = await fetch(tokenEventsUrl(input.sceneId, cursor), {
    method: "GET",
    headers: buildVttRequestHeaders({
      accept: "text/event-stream",
      bearerToken: input.bearerToken,
    }),
    signal: input.signal,
  });
  if (!response.ok) await responseJson(response);
  if (!response.body) {
    throw new VttApiError("The token event stream has no response body.", {
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
      const event = parseTokenSseBlock(buffer.slice(0, boundary.index));
      buffer = buffer.slice(boundary.index + boundary.length);
      if (event && event.sequence > cursor) {
        cursor = event.sequence;
        input.onEvent(event);
      }
      boundary = findSseBoundary(buffer);
    }
    if (done) break;
  }
  if (buffer.trim() !== "") throw new Error("Token SSE ended with an incomplete event");
  return cursor;
}
