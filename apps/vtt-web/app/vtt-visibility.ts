import { VTT_API_BASE_URL, VttApiError, type JsonValue } from "./vtt-client";
import { buildVttRequestHeaders } from "./vtt-transport";
import { parseTokenRecord, type TokenRecord } from "./vtt-tokens";

export interface VisibilityPoint {
  x_ft: number;
  y_ft: number;
}

interface VisibilityRecordBase {
  record_id: string;
  scene_id: string;
}

export interface SightBarrier extends VisibilityRecordBase {
  schema_version: "vtt.sight_barrier.v1";
  record_type: "barrier";
  start: VisibilityPoint;
  end: VisibilityPoint;
  behavior: "wall" | "window" | "door";
  blocks_sight: boolean;
  blocks_movement: boolean;
  portal_state: "open" | "closed" | null;
}

export interface LightEmitter extends VisibilityRecordBase {
  schema_version: "vtt.light_emitter.v1";
  record_type: "light";
  origin: VisibilityPoint;
  bright_radius_ft: number;
  dim_radius_ft: number;
  shape: "circle" | "cone";
  direction_degrees: number;
  angle_degrees: number;
  audience: string[];
}

export interface SceneEnvironment extends VisibilityRecordBase {
  schema_version: "vtt.scene_environment.v1";
  record_type: "environment";
  darkness: "bright" | "dim" | "darkness";
  shared_vision: "owned_only" | "party";
}

export interface TokenVision extends VisibilityRecordBase {
  schema_version: "vtt.token_vision.v1";
  record_type: "token_vision";
  token_id: string;
  enabled: boolean;
  normal_range_ft: number;
  darkvision_range_ft: number;
  emitted_bright_radius_ft: number;
  emitted_dim_radius_ft: number;
}

export interface FogOperation extends VisibilityRecordBase {
  schema_version: "vtt.fog_operation.v1";
  record_type: "fog_operation";
  operation_index: number;
  operation: "reveal" | "hide";
  polygon: VisibilityPoint[];
  inverse_of: string | null;
}

export type VisibilityRecord =
  | SightBarrier
  | LightEmitter
  | SceneEnvironment
  | TokenVision
  | FogOperation;

export interface VisibilityCatalogView {
  schema_version: "vtt.visibility_catalog_view.v1";
  table_id: string;
  scene_id: string;
  revision: number;
  records: VisibilityRecord[];
}

export interface VisibilityMaskRun {
  schema_version: "vtt.visibility_mask_run.v1";
  start: number;
  length: number;
}

export interface VisibilityProjection {
  schema_version: "vtt.visibility_projection.v1";
  table_id: string;
  scene_id: string;
  scene_revision: number;
  token_revision: number;
  visibility_revision: number;
  encounter_revision: number;
  mask_width: number;
  mask_height: number;
  visible_runs: VisibilityMaskRun[];
  tokens: TokenRecord[];
}

export interface VisibilityProjectionSources {
  sceneId: string | null;
  sceneRevision: number | null;
  tokenRevision: number | null;
  visibilityRevision: number | null;
  encounterRevision: number | null;
}

export function visibilityProjectionMatchesSources(
  projection: VisibilityProjection | null,
  sources: VisibilityProjectionSources,
): projection is VisibilityProjection {
  return projection !== null &&
    sources.sceneId !== null &&
    sources.sceneRevision !== null &&
    sources.tokenRevision !== null &&
    sources.visibilityRevision !== null &&
    sources.encounterRevision !== null &&
    projection.scene_id === sources.sceneId &&
    projection.scene_revision === sources.sceneRevision &&
    projection.token_revision === sources.tokenRevision &&
    projection.visibility_revision === sources.visibilityRevision &&
    projection.encounter_revision === sources.encounterRevision;
}

interface VisibilityCommandBase {
  schema_version: "vtt.visibility_command.v1";
  table_id: string;
  command_id: string;
  expected_revision: number;
}

export type VisibilityCommand =
  | (VisibilityCommandBase & { command_type: "put"; record: VisibilityRecord })
  | (VisibilityCommandBase & {
      command_type: "delete";
      scene_id: string;
      record_id: string;
    })
  | (VisibilityCommandBase & {
      command_type: "set_door_state";
      scene_id: string;
      barrier_id: string;
      portal_state: "open" | "closed";
    })
  | (VisibilityCommandBase & {
      command_type: "undo_fog";
      scene_id: string;
      target_record_id: string;
      inverse_record_id: string;
    });

export interface VisibilityRequest {
  schema_version: "vtt.visibility_request.v1";
  session_id: string;
  command: VisibilityCommand;
}

export interface VisibilityResponse {
  schema_version: "vtt.visibility_response.v1";
  session_id: string;
  table_id: string;
  command_id: string;
  revision: number;
  replayed: boolean;
  event: Record<string, unknown>;
}

export interface VisibilityChangeSignal {
  schema_version: "vtt.visibility_change_signal.v1";
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

function text(value: unknown, path: string, maximum = 128): string {
  if (
    typeof value !== "string" ||
    value.length === 0 ||
    value.trim() !== value ||
    value.length > maximum
  ) throw new Error(`${path} must be canonical text`);
  return value;
}

function identifier(value: unknown, path: string): string {
  const result = text(value, path);
  if (!/^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/.test(result)) {
    throw new Error(`${path} must be a URL-safe identifier`);
  }
  return result;
}

function finite(value: unknown, path: string, minimum = -1_000_000, maximum = 1_000_000): number {
  if (
    typeof value !== "number" ||
    !Number.isFinite(value) ||
    value < minimum ||
    value > maximum
  ) throw new Error(`${path} must be a bounded finite number`);
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

function literal<T extends string>(value: unknown, options: readonly T[], path: string): T {
  if (typeof value !== "string" || !options.includes(value as T)) {
    throw new Error(`${path} has an unsupported value`);
  }
  return value as T;
}

function compareCodePoints(left: string, right: string): number {
  const a = Array.from(left, (value) => value.codePointAt(0) as number);
  const b = Array.from(right, (value) => value.codePointAt(0) as number);
  for (let index = 0; index < Math.min(a.length, b.length); index += 1) {
    if (a[index] !== b[index]) return a[index] - b[index];
  }
  return a.length - b.length;
}

function point(value: unknown, path: string): VisibilityPoint {
  const data = exactObject(value, ["x_ft", "y_ft"], path);
  return {
    x_ft: finite(data.x_ft, `${path}.x_ft`),
    y_ft: finite(data.y_ft, `${path}.y_ft`),
  };
}

export function parseVisibilityRecord(value: unknown, path = "visibility_record"): VisibilityRecord {
  const base = objectValue(value, path);
  const recordType = literal(
    base.record_type,
    ["barrier", "light", "environment", "token_vision", "fog_operation"],
    `${path}.record_type`,
  );
  const recordId = identifier(base.record_id, `${path}.record_id`);
  const sceneId = identifier(base.scene_id, `${path}.scene_id`);
  if (recordType === "barrier") {
    const data = exactObject(value, [
      "schema_version", "record_type", "record_id", "scene_id", "start", "end",
      "behavior", "blocks_sight", "blocks_movement", "portal_state",
    ], path);
    const behavior = literal(data.behavior, ["wall", "window", "door"], `${path}.behavior`);
    const portalState = data.portal_state === null
      ? null
      : literal(data.portal_state, ["open", "closed"], `${path}.portal_state`);
    if ((behavior === "door") !== (portalState !== null)) {
      throw new Error(`${path}.portal_state does not match barrier behavior`);
    }
    return {
      schema_version: literal(data.schema_version, ["vtt.sight_barrier.v1"], `${path}.schema_version`),
      record_type: "barrier", record_id: recordId, scene_id: sceneId,
      start: point(data.start, `${path}.start`), end: point(data.end, `${path}.end`), behavior,
      blocks_sight: booleanValue(data.blocks_sight, `${path}.blocks_sight`),
      blocks_movement: booleanValue(data.blocks_movement, `${path}.blocks_movement`),
      portal_state: portalState,
    };
  }
  if (recordType === "light") {
    const data = exactObject(value, [
      "schema_version", "record_type", "record_id", "scene_id", "origin",
      "bright_radius_ft", "dim_radius_ft", "shape", "direction_degrees",
      "angle_degrees", "audience",
    ], path);
    if (!Array.isArray(data.audience) || data.audience.length === 0) {
      throw new Error(`${path}.audience must be a non-empty ordered list`);
    }
    const audience = data.audience.map((entry, index) =>
      text(entry, `${path}.audience[${index}]`));
    const bright = finite(data.bright_radius_ft, `${path}.bright_radius_ft`, 0, 100_000);
    const dim = finite(data.dim_radius_ft, `${path}.dim_radius_ft`, 0, 100_000);
    if (dim < bright || dim === 0) throw new Error(`${path} light radii are inconsistent`);
    return {
      schema_version: literal(data.schema_version, ["vtt.light_emitter.v1"], `${path}.schema_version`),
      record_type: "light", record_id: recordId, scene_id: sceneId,
      origin: point(data.origin, `${path}.origin`), bright_radius_ft: bright,
      dim_radius_ft: dim,
      shape: literal(data.shape, ["circle", "cone"], `${path}.shape`),
      direction_degrees: finite(data.direction_degrees, `${path}.direction_degrees`, 0, 359.999999),
      angle_degrees: finite(data.angle_degrees, `${path}.angle_degrees`, Number.MIN_VALUE, 360),
      audience,
    };
  }
  if (recordType === "environment") {
    const data = exactObject(value, [
      "schema_version", "record_type", "record_id", "scene_id", "darkness", "shared_vision",
    ], path);
    if (recordId !== "scene-environment") throw new Error(`${path}.record_id is not canonical`);
    return {
      schema_version: literal(data.schema_version, ["vtt.scene_environment.v1"], `${path}.schema_version`),
      record_type: "environment", record_id: recordId, scene_id: sceneId,
      darkness: literal(data.darkness, ["bright", "dim", "darkness"], `${path}.darkness`),
      shared_vision: literal(data.shared_vision, ["owned_only", "party"], `${path}.shared_vision`),
    };
  }
  if (recordType === "token_vision") {
    const data = exactObject(value, [
      "schema_version", "record_type", "record_id", "scene_id", "token_id", "enabled",
      "normal_range_ft", "darkvision_range_ft", "emitted_bright_radius_ft", "emitted_dim_radius_ft",
    ], path);
    const emittedBright = finite(data.emitted_bright_radius_ft, `${path}.emitted_bright_radius_ft`, 0, 100_000);
    const emittedDim = finite(data.emitted_dim_radius_ft, `${path}.emitted_dim_radius_ft`, 0, 100_000);
    if (emittedDim < emittedBright) throw new Error(`${path} emitted radii are inconsistent`);
    return {
      schema_version: literal(data.schema_version, ["vtt.token_vision.v1"], `${path}.schema_version`),
      record_type: "token_vision", record_id: recordId, scene_id: sceneId,
      token_id: identifier(data.token_id, `${path}.token_id`),
      enabled: booleanValue(data.enabled, `${path}.enabled`),
      normal_range_ft: finite(data.normal_range_ft, `${path}.normal_range_ft`, 0, 100_000),
      darkvision_range_ft: finite(data.darkvision_range_ft, `${path}.darkvision_range_ft`, 0, 100_000),
      emitted_bright_radius_ft: emittedBright,
      emitted_dim_radius_ft: emittedDim,
    };
  }
  const data = exactObject(value, [
    "schema_version", "record_type", "record_id", "scene_id", "operation_index",
    "operation", "polygon", "inverse_of",
  ], path);
  if (!Array.isArray(data.polygon) || data.polygon.length < 3 || data.polygon.length > 128) {
    throw new Error(`${path}.polygon must be a bounded ordered list`);
  }
  return {
    schema_version: literal(data.schema_version, ["vtt.fog_operation.v1"], `${path}.schema_version`),
    record_type: "fog_operation", record_id: recordId, scene_id: sceneId,
    operation_index: integer(data.operation_index, `${path}.operation_index`, 1, 2_000),
    operation: literal(data.operation, ["reveal", "hide"], `${path}.operation`),
    polygon: data.polygon.map((entry, index) => point(entry, `${path}.polygon[${index}]`)),
    inverse_of: data.inverse_of === null ? null : identifier(data.inverse_of, `${path}.inverse_of`),
  };
}

export function parseVisibilityCatalog(value: unknown): VisibilityCatalogView {
  const data = exactObject(
    value,
    ["schema_version", "table_id", "scene_id", "revision", "records"],
    "visibility_catalog",
  );
  if (!Array.isArray(data.records)) throw new Error("visibility_catalog.records must be ordered");
  const sceneId = identifier(data.scene_id, "visibility_catalog.scene_id");
  const records = data.records.map((record, index) =>
    parseVisibilityRecord(record, `visibility_catalog.records[${index}]`));
  const ids = records.map((record) => record.record_id);
  if (
    records.some((record) => record.scene_id !== sceneId) ||
    new Set(ids).size !== ids.length ||
    ids.some((id, index) => index > 0 && compareCodePoints(ids[index - 1], id) > 0)
  ) throw new Error("visibility_catalog records must be unique, sorted, and scene-bound");
  return {
    schema_version: literal(data.schema_version, ["vtt.visibility_catalog_view.v1"], "visibility_catalog.schema_version"),
    table_id: identifier(data.table_id, "visibility_catalog.table_id"),
    scene_id: sceneId,
    revision: integer(data.revision, "visibility_catalog.revision"),
    records,
  };
}

export function parseVisibilityProjection(value: unknown): VisibilityProjection {
  const data = exactObject(value, [
    "schema_version", "table_id", "scene_id", "scene_revision", "token_revision",
    "visibility_revision", "encounter_revision", "mask_width", "mask_height",
    "visible_runs", "tokens",
  ], "visibility_projection");
  const width = integer(data.mask_width, "visibility_projection.mask_width", 1);
  const height = integer(data.mask_height, "visibility_projection.mask_height", 1);
  const sampleCount = width * height;
  if (sampleCount > 65_536) throw new Error("visibility_projection exceeds the mask budget");
  if (!Array.isArray(data.visible_runs)) throw new Error("visibility_projection.visible_runs must be ordered");
  let previousEnd = 0;
  const runs = data.visible_runs.map((value, index): VisibilityMaskRun => {
    const run = exactObject(value, ["schema_version", "start", "length"], `visibility_projection.visible_runs[${index}]`);
    const start = integer(run.start, `visibility_projection.visible_runs[${index}].start`);
    const length = integer(run.length, `visibility_projection.visible_runs[${index}].length`, 1);
    if (start + length > sampleCount || (index > 0 && start <= previousEnd)) {
      throw new Error("visibility_projection runs overlap or leave bounds");
    }
    previousEnd = start + length;
    return {
      schema_version: literal(run.schema_version, ["vtt.visibility_mask_run.v1"], `visibility_projection.visible_runs[${index}].schema_version`),
      start,
      length,
    };
  });
  if (!Array.isArray(data.tokens)) throw new Error("visibility_projection.tokens must be ordered");
  const sceneId = identifier(data.scene_id, "visibility_projection.scene_id");
  const tokens = data.tokens.map((token, index) =>
    parseTokenRecord(token, `visibility_projection.tokens[${index}]`));
  const tokenIds = tokens.map((token) => token.token_id);
  if (
    tokens.some((token) => token.scene_id !== sceneId) ||
    new Set(tokenIds).size !== tokenIds.length ||
    tokenIds.some((id, index) => index > 0 && compareCodePoints(tokenIds[index - 1], id) > 0)
  ) throw new Error("visibility_projection tokens must be unique, sorted, and scene-bound");
  return {
    schema_version: literal(data.schema_version, ["vtt.visibility_projection.v1"], "visibility_projection.schema_version"),
    table_id: identifier(data.table_id, "visibility_projection.table_id"),
    scene_id: sceneId,
    scene_revision: integer(data.scene_revision, "visibility_projection.scene_revision"),
    token_revision: integer(data.token_revision, "visibility_projection.token_revision"),
    visibility_revision: integer(data.visibility_revision, "visibility_projection.visibility_revision"),
    encounter_revision: integer(data.encounter_revision, "visibility_projection.encounter_revision"),
    mask_width: width,
    mask_height: height,
    visible_runs: runs,
    tokens,
  };
}

export function expandVisibilityMask(projection: VisibilityProjection): Uint8Array {
  const parsed = parseVisibilityProjection(projection);
  const mask = new Uint8Array(parsed.mask_width * parsed.mask_height);
  for (const run of parsed.visible_runs) mask.fill(1, run.start, run.start + run.length);
  return mask;
}

async function responseJson(response: Response): Promise<unknown> {
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    const data = payload && typeof payload === "object" ? payload as Record<string, unknown> : {};
    throw new VttApiError(
      typeof data.message === "string" ? data.message : "The visibility request failed.",
      {
        code: typeof data.code === "string" ? data.code : "http_error",
        status: response.status,
        details: data.details && typeof data.details === "object" ? data.details as Record<string, JsonValue> : {},
      },
    );
  }
  return payload;
}

function visibilityUrl(sceneId?: string): string {
  if (!sceneId) return `${VTT_API_BASE_URL}/api/v1/visibility`;
  return `${VTT_API_BASE_URL}/api/v1/visibility?${new URLSearchParams({ scene_id: identifier(sceneId, "sceneId") })}`;
}

export async function getVisibilityCatalog(sceneId?: string, signal?: AbortSignal, bearerToken?: string | null): Promise<VisibilityCatalogView> {
  const response = await fetch(visibilityUrl(sceneId), {
    method: "GET",
    headers: buildVttRequestHeaders({ accept: "application/json", bearerToken }),
    signal,
  });
  return parseVisibilityCatalog(await responseJson(response));
}

export async function getVisibilityProjection(signal?: AbortSignal, bearerToken?: string | null): Promise<VisibilityProjection> {
  const response = await fetch(visibilityUrl(), {
    method: "GET",
    headers: buildVttRequestHeaders({ accept: "application/json", bearerToken }),
    signal,
  });
  return parseVisibilityProjection(await responseJson(response));
}

export async function getVisibilityPreview(participantId: string, signal?: AbortSignal, bearerToken?: string | null): Promise<VisibilityProjection> {
  const query = new URLSearchParams({ participant_id: identifier(participantId, "participantId") });
  const response = await fetch(`${VTT_API_BASE_URL}/api/v1/visibility-preview?${query}`, {
    method: "GET",
    headers: buildVttRequestHeaders({ accept: "application/json", bearerToken }),
    signal,
  });
  return parseVisibilityProjection(await responseJson(response));
}

function commandBase(input: { tableId: string; expectedRevision: number; commandId?: string }): VisibilityCommandBase {
  return {
    schema_version: "vtt.visibility_command.v1",
    table_id: identifier(input.tableId, "tableId"),
    command_id: identifier(input.commandId ?? crypto.randomUUID(), "commandId"),
    expected_revision: integer(input.expectedRevision, "expectedRevision"),
  };
}

function request(sessionId: string, command: VisibilityCommand): VisibilityRequest {
  return { schema_version: "vtt.visibility_request.v1", session_id: text(sessionId, "sessionId"), command };
}

export function buildVisibilityPutRequest(input: { sessionId: string; tableId: string; expectedRevision: number; commandId?: string; record: VisibilityRecord }): VisibilityRequest {
  return request(input.sessionId, { ...commandBase(input), command_type: "put", record: input.record });
}

export function buildVisibilityDeleteRequest(input: { sessionId: string; tableId: string; expectedRevision: number; commandId?: string; sceneId: string; recordId: string }): VisibilityRequest {
  return request(input.sessionId, {
    ...commandBase(input), command_type: "delete",
    scene_id: identifier(input.sceneId, "sceneId"), record_id: identifier(input.recordId, "recordId"),
  });
}

export function buildDoorStateRequest(input: { sessionId: string; tableId: string; expectedRevision: number; commandId?: string; sceneId: string; barrierId: string; portalState: "open" | "closed" }): VisibilityRequest {
  return request(input.sessionId, {
    ...commandBase(input), command_type: "set_door_state",
    scene_id: identifier(input.sceneId, "sceneId"), barrier_id: identifier(input.barrierId, "barrierId"), portal_state: input.portalState,
  });
}

export function buildFogUndoRequest(input: { sessionId: string; tableId: string; expectedRevision: number; commandId?: string; sceneId: string; targetRecordId: string; inverseRecordId?: string }): VisibilityRequest {
  return request(input.sessionId, {
    ...commandBase(input), command_type: "undo_fog",
    scene_id: identifier(input.sceneId, "sceneId"),
    target_record_id: identifier(input.targetRecordId, "targetRecordId"),
    inverse_record_id: identifier(input.inverseRecordId ?? `fog-${crypto.randomUUID()}`, "inverseRecordId"),
  });
}

export async function postVisibilityRequest(payload: VisibilityRequest, signal?: AbortSignal, bearerToken?: string | null): Promise<VisibilityResponse> {
  const response = await fetch(`${VTT_API_BASE_URL}/api/v1/visibility-commands`, {
    method: "POST",
    headers: buildVttRequestHeaders({ accept: "application/json", contentType: "application/json", bearerToken }),
    body: JSON.stringify(payload),
    signal,
  });
  const data = exactObject(await responseJson(response), [
    "schema_version", "session_id", "table_id", "command_id", "revision", "replayed", "event",
  ], "visibility_response");
  return {
    schema_version: literal(data.schema_version, ["vtt.visibility_response.v1"], "visibility_response.schema_version"),
    session_id: text(data.session_id, "visibility_response.session_id"),
    table_id: identifier(data.table_id, "visibility_response.table_id"),
    command_id: identifier(data.command_id, "visibility_response.command_id"),
    revision: integer(data.revision, "visibility_response.revision", 1),
    replayed: booleanValue(data.replayed, "visibility_response.replayed"),
    event: objectValue(data.event, "visibility_response.event"),
  };
}

export function parseVisibilityChangeSignal(value: unknown): VisibilityChangeSignal {
  const data = exactObject(value, ["schema_version", "sequence", "revision", "scene_id"], "visibility_change_signal");
  const sequence = integer(data.sequence, "visibility_change_signal.sequence", 1);
  const revision = integer(data.revision, "visibility_change_signal.revision", 1);
  if (sequence !== revision) throw new Error("visibility signal sequence must match revision");
  return {
    schema_version: literal(data.schema_version, ["vtt.visibility_change_signal.v1"], "visibility_change_signal.schema_version"),
    sequence, revision, scene_id: identifier(data.scene_id, "visibility_change_signal.scene_id"),
  };
}

export function visibilityEventsUrl(sceneId: string, after: number): string {
  const query = new URLSearchParams({ scene_id: identifier(sceneId, "sceneId"), after: String(integer(after, "after")) });
  return `${VTT_API_BASE_URL}/api/v1/visibility-events?${query}`;
}

export function parseVisibilitySseBlock(block: string): VisibilityChangeSignal | null {
  if (typeof block !== "string") throw new Error("Visibility SSE block must be text");
  const fields = new Map<string, string>();
  for (const rawLine of block.replaceAll("\r\n", "\n").split("\n")) {
    if (!rawLine || rawLine.startsWith(":")) continue;
    const separator = rawLine.indexOf(":");
    if (separator <= 0) throw new Error("Visibility SSE contains a malformed field");
    const name = rawLine.slice(0, separator);
    const value = rawLine.slice(separator + 1).replace(/^ /, "");
    if (!["id", "event", "data"].includes(name) || fields.has(name)) {
      throw new Error("Visibility SSE contains duplicate or unsupported fields");
    }
    fields.set(name, value);
  }
  if (fields.size === 0) return null;
  if (fields.get("event") !== "vtt.visibility_changed") throw new Error("Visibility SSE event type is invalid");
  const idText = fields.get("id");
  const dataText = fields.get("data");
  if (!idText || !dataText || !/^\d+$/.test(idText)) throw new Error("Visibility SSE id is invalid");
  const id = Number(idText);
  if (!Number.isSafeInteger(id) || String(id) !== idText) throw new Error("Visibility SSE id is not canonical");
  let decoded: unknown;
  try { decoded = JSON.parse(dataText); } catch { throw new Error("Visibility SSE data must be JSON"); }
  const signal = parseVisibilityChangeSignal(decoded);
  if (signal.sequence !== id) throw new Error("Visibility SSE id must match sequence");
  return signal;
}

function findBoundary(buffer: string): { index: number; length: number } | null {
  const unix = buffer.indexOf("\n\n");
  const windows = buffer.indexOf("\r\n\r\n");
  if (unix < 0 && windows < 0) return null;
  if (windows >= 0 && (unix < 0 || windows < unix)) return { index: windows, length: 4 };
  return { index: unix, length: 2 };
}

export async function streamVisibilityEvents(input: {
  sceneId: string;
  after: number;
  bearerToken?: string | null;
  signal: AbortSignal;
  onEvent: (event: VisibilityChangeSignal) => void;
  onOpen?: () => void;
}): Promise<number> {
  let cursor = integer(input.after, "after");
  const response = await fetch(visibilityEventsUrl(input.sceneId, cursor), {
    method: "GET",
    headers: buildVttRequestHeaders({ accept: "text/event-stream", bearerToken: input.bearerToken }),
    signal: input.signal,
  });
  if (!response.ok) await responseJson(response);
  if (!response.body) throw new VttApiError("The visibility stream has no body.", { code: "invalid_response", status: response.status });
  input.onOpen?.();
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    let boundary = findBoundary(buffer);
    while (boundary) {
      const event = parseVisibilitySseBlock(buffer.slice(0, boundary.index));
      buffer = buffer.slice(boundary.index + boundary.length);
      if (event && event.sequence > cursor) { cursor = event.sequence; input.onEvent(event); }
      boundary = findBoundary(buffer);
    }
    if (done) break;
  }
  if (buffer.trim()) throw new Error("Visibility SSE ended with an incomplete event");
  return cursor;
}
