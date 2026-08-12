import {
  VTT_API_BASE_URL,
  VttApiError,
  type JsonValue,
} from "./vtt-client";
import { buildVttRequestHeaders } from "./vtt-transport";

export interface SceneMapMetadata {
  schema_version: "vtt.scene_map_metadata.v1";
  name: string;
  width_px: number;
  height_px: number;
  grid_size_px: number;
  gridless: boolean;
}

export interface SceneRecord {
  schema_version: "vtt.scene_record.v1";
  scene_id: string;
  map_metadata: SceneMapMetadata;
}

export interface SceneLibraryEntry {
  scene: SceneRecord;
  archived: boolean;
}

export interface SceneLibraryView {
  schema_version: "vtt.scene_library_view.v1";
  table_id: string;
  revision: number;
  active_scene_id: string | null;
  scenes: SceneLibraryEntry[];
}

export interface SceneExportBundle {
  schema_version: "vtt.scene_export.v1";
  scene: SceneRecord;
}

interface SceneCommandBase {
  schema_version: "vtt.scene_command.v1";
  table_id: string;
  command_id: string;
  expected_revision: number;
}

export interface SceneCreateCommand extends SceneCommandBase {
  command_type: "create";
  scene: SceneRecord;
}

export interface SceneDuplicateCommand extends SceneCommandBase {
  command_type: "duplicate";
  source_scene_id: string;
  new_scene_id: string;
  new_name: string;
}

export interface SceneActivateCommand extends SceneCommandBase {
  command_type: "activate";
  scene_id: string;
}

export interface SceneArchiveCommand extends SceneCommandBase {
  command_type: "archive";
  scene_id: string;
  successor_scene_id: string | null;
}

export interface SceneImportCommand extends SceneCommandBase {
  command_type: "import";
  bundle: SceneExportBundle;
}

export type SceneMutationCommand =
  | SceneCreateCommand
  | SceneDuplicateCommand
  | SceneActivateCommand
  | SceneArchiveCommand
  | SceneImportCommand;

export interface SceneLibraryRequest {
  schema_version: "vtt.scene_library_request.v1";
  session_id: string;
  command: SceneMutationCommand;
}

interface SceneEventBase {
  schema_version: "vtt.scene_event.v1";
  table_id: string;
  event_id: string;
  sequence: number;
  revision: number;
  command_id: string;
}

export type SceneEvent =
  | (SceneEventBase & {
      event_type: "created";
      scene: SceneRecord;
      became_active: boolean;
    })
  | (SceneEventBase & {
      event_type: "duplicated";
      source_scene_id: string;
      scene: SceneRecord;
      became_active: boolean;
    })
  | (SceneEventBase & {
      event_type: "activated";
      scene_id: string;
      previous_scene_id: string;
    })
  | (SceneEventBase & {
      event_type: "archived";
      scene_id: string;
      successor_scene_id: string | null;
      active_scene_id: string;
    })
  | (SceneEventBase & {
      event_type: "imported";
      scene: SceneRecord;
      became_active: boolean;
    });

export interface SceneLibraryResponse {
  schema_version: "vtt.scene_library_response.v1";
  session_id: string;
  table_id: string;
  command_id: string;
  revision: number;
  replayed: boolean;
  event: SceneEvent;
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

function literal<T extends string>(
  value: unknown,
  allowed: readonly T[],
  path: string,
): T {
  if (typeof value !== "string" || !allowed.includes(value as T)) {
    throw new Error(`${path} must be one of ${allowed.join(", ")}`);
  }
  return value as T;
}

function canonicalText(value: unknown, path: string, maximum = 128): string {
  if (
    typeof value !== "string" ||
    value.length === 0 ||
    value.trim() !== value ||
    Array.from(value).length > maximum
  ) {
    throw new Error(`${path} must be canonical non-empty text`);
  }
  return value;
}

function integer(value: unknown, path: string, minimum = 0, maximum?: number): number {
  if (
    typeof value !== "number" ||
    !Number.isSafeInteger(value) ||
    value < minimum ||
    (maximum !== undefined && value > maximum)
  ) {
    throw new Error(`${path} must be a safe integer in range`);
  }
  return value;
}

function finiteNumber(
  value: unknown,
  path: string,
  minimumExclusive: number,
  maximum: number,
): number {
  if (
    typeof value !== "number" ||
    !Number.isFinite(value) ||
    value <= minimumExclusive ||
    value > maximum
  ) {
    throw new Error(`${path} must be a finite number in range`);
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
  for (
    let index = 0;
    index < Math.min(leftPoints.length, rightPoints.length);
    index += 1
  ) {
    if (leftPoints[index] !== rightPoints[index]) {
      return leftPoints[index] - rightPoints[index];
    }
  }
  return leftPoints.length - rightPoints.length;
}

function parseMapMetadata(value: unknown, path: string): SceneMapMetadata {
  const data = exactObject(
    value,
    [
      "schema_version",
      "name",
      "width_px",
      "height_px",
      "grid_size_px",
      "gridless",
    ],
    path,
  );
  return {
    schema_version: literal(
      data.schema_version,
      ["vtt.scene_map_metadata.v1"],
      `${path}.schema_version`,
    ),
    name: canonicalText(data.name, `${path}.name`, 160),
    width_px: integer(data.width_px, `${path}.width_px`, 1, 1_000_000),
    height_px: integer(data.height_px, `${path}.height_px`, 1, 1_000_000),
    grid_size_px: finiteNumber(
      data.grid_size_px,
      `${path}.grid_size_px`,
      0,
      100_000,
    ),
    gridless: booleanValue(data.gridless, `${path}.gridless`),
  };
}

export function parseSceneRecord(value: unknown, path = "scene"): SceneRecord {
  const data = exactObject(
    value,
    ["schema_version", "scene_id", "map_metadata"],
    path,
  );
  return {
    schema_version: literal(
      data.schema_version,
      ["vtt.scene_record.v1"],
      `${path}.schema_version`,
    ),
    scene_id: canonicalText(data.scene_id, `${path}.scene_id`),
    map_metadata: parseMapMetadata(data.map_metadata, `${path}.map_metadata`),
  };
}

export function parseSceneLibraryView(value: unknown): SceneLibraryView {
  const data = exactObject(
    value,
    ["schema_version", "table_id", "revision", "active_scene_id", "scenes"],
    "scene_library_view",
  );
  if (!Array.isArray(data.scenes)) {
    throw new Error("scene_library_view.scenes must be an ordered list");
  }
  const scenes = data.scenes.map((rawEntry, index) => {
    const entry = exactObject(
      rawEntry,
      ["scene", "archived"],
      `scene_library_view.scenes[${index}]`,
    );
    return {
      scene: parseSceneRecord(
        entry.scene,
        `scene_library_view.scenes[${index}].scene`,
      ),
      archived: booleanValue(
        entry.archived,
        `scene_library_view.scenes[${index}].archived`,
      ),
    };
  });
  const sceneIds = scenes.map((entry) => entry.scene.scene_id);
  if (
    new Set(sceneIds).size !== sceneIds.length ||
    sceneIds.some(
      (sceneId, index) =>
        index > 0 && compareCodePoints(sceneIds[index - 1], sceneId) > 0,
    )
  ) {
    throw new Error("scene_library_view scenes must have unique sorted scene IDs");
  }
  const activeSceneId =
    data.active_scene_id === null
      ? null
      : canonicalText(data.active_scene_id, "scene_library_view.active_scene_id");
  const availableIds = new Set(
    scenes.filter((entry) => !entry.archived).map((entry) => entry.scene.scene_id),
  );
  if (
    (availableIds.size === 0 && activeSceneId !== null) ||
    (availableIds.size > 0 &&
      (activeSceneId === null || !availableIds.has(activeSceneId)))
  ) {
    throw new Error("scene_library_view active scene must identify one available scene");
  }
  return {
    schema_version: literal(
      data.schema_version,
      ["vtt.scene_library_view.v1"],
      "scene_library_view.schema_version",
    ),
    table_id: canonicalText(data.table_id, "scene_library_view.table_id"),
    revision: integer(data.revision, "scene_library_view.revision"),
    active_scene_id: activeSceneId,
    scenes,
  };
}

export function buildSceneExportBundle(scene: SceneRecord): SceneExportBundle {
  return {
    schema_version: "vtt.scene_export.v1",
    scene: parseSceneRecord(scene),
  };
}

export function parseSceneExportBundle(value: string | unknown): SceneExportBundle {
  let decoded = value;
  if (typeof value === "string") {
    try {
      decoded = JSON.parse(value);
    } catch {
      throw new Error("scene_export must be valid JSON");
    }
  }
  const data = exactObject(decoded, ["schema_version", "scene"], "scene_export");
  return {
    schema_version: literal(
      data.schema_version,
      ["vtt.scene_export.v1"],
      "scene_export.schema_version",
    ),
    scene: parseSceneRecord(data.scene, "scene_export.scene"),
  };
}

function request(
  sessionId: string,
  command: SceneMutationCommand,
): SceneLibraryRequest {
  return {
    schema_version: "vtt.scene_library_request.v1",
    session_id: canonicalText(sessionId, "sessionId"),
    command,
  };
}

function commandBase(input: {
  tableId: string;
  expectedRevision: number;
  commandId?: string;
}): SceneCommandBase {
  return {
    schema_version: "vtt.scene_command.v1",
    table_id: canonicalText(input.tableId, "tableId"),
    command_id: canonicalText(input.commandId ?? crypto.randomUUID(), "commandId"),
    expected_revision: integer(input.expectedRevision, "expectedRevision"),
  };
}

export function buildSceneCreateRequest(input: {
  sessionId: string;
  tableId: string;
  expectedRevision: number;
  scene: SceneRecord;
  commandId?: string;
}): SceneLibraryRequest {
  return request(input.sessionId, {
    ...commandBase(input),
    command_type: "create",
    scene: parseSceneRecord(input.scene),
  });
}

export function buildSceneDuplicateRequest(input: {
  sessionId: string;
  tableId: string;
  expectedRevision: number;
  sourceSceneId: string;
  newSceneId: string;
  newName: string;
  commandId?: string;
}): SceneLibraryRequest {
  const sourceSceneId = canonicalText(input.sourceSceneId, "sourceSceneId");
  const newSceneId = canonicalText(input.newSceneId, "newSceneId");
  if (sourceSceneId === newSceneId) {
    throw new Error("newSceneId must differ from sourceSceneId");
  }
  return request(input.sessionId, {
    ...commandBase(input),
    command_type: "duplicate",
    source_scene_id: sourceSceneId,
    new_scene_id: newSceneId,
    new_name: canonicalText(input.newName, "newName", 160),
  });
}

export function buildSceneActivateRequest(input: {
  sessionId: string;
  tableId: string;
  expectedRevision: number;
  sceneId: string;
  commandId?: string;
}): SceneLibraryRequest {
  return request(input.sessionId, {
    ...commandBase(input),
    command_type: "activate",
    scene_id: canonicalText(input.sceneId, "sceneId"),
  });
}

export function buildSceneArchiveRequest(input: {
  sessionId: string;
  tableId: string;
  expectedRevision: number;
  sceneId: string;
  successorSceneId?: string | null;
  commandId?: string;
}): SceneLibraryRequest {
  const sceneId = canonicalText(input.sceneId, "sceneId");
  const successorSceneId =
    input.successorSceneId === null || input.successorSceneId === undefined
      ? null
      : canonicalText(input.successorSceneId, "successorSceneId");
  if (sceneId === successorSceneId) {
    throw new Error("successorSceneId must differ from sceneId");
  }
  return request(input.sessionId, {
    ...commandBase(input),
    command_type: "archive",
    scene_id: sceneId,
    successor_scene_id: successorSceneId,
  });
}

export function buildSceneImportRequest(input: {
  sessionId: string;
  tableId: string;
  expectedRevision: number;
  bundle: SceneExportBundle;
  commandId?: string;
}): SceneLibraryRequest {
  return request(input.sessionId, {
    ...commandBase(input),
    command_type: "import",
    bundle: parseSceneExportBundle(input.bundle),
  });
}

export function parseSceneEvent(value: unknown): SceneEvent {
  const base = objectValue(value, "scene_event");
  const eventType = literal(
    base.event_type,
    ["created", "duplicated", "activated", "archived", "imported"],
    "scene_event.event_type",
  );
  const commonKeys = [
    "schema_version",
    "table_id",
    "event_id",
    "sequence",
    "revision",
    "command_id",
    "event_type",
  ];
  const variantKeys =
    eventType === "created" || eventType === "imported"
      ? ["scene", "became_active"]
      : eventType === "duplicated"
        ? ["source_scene_id", "scene", "became_active"]
        : eventType === "activated"
          ? ["scene_id", "previous_scene_id"]
          : ["scene_id", "successor_scene_id", "active_scene_id"];
  const data = exactObject(value, [...commonKeys, ...variantKeys], "scene_event");
  const sequence = integer(data.sequence, "scene_event.sequence", 1);
  const revision = integer(data.revision, "scene_event.revision", 1);
  if (sequence !== revision) {
    throw new Error("scene_event sequence must match revision");
  }
  const common = {
    schema_version: literal(
      data.schema_version,
      ["vtt.scene_event.v1"],
      "scene_event.schema_version",
    ),
    table_id: canonicalText(data.table_id, "scene_event.table_id"),
    event_id: canonicalText(data.event_id, "scene_event.event_id", 512),
    sequence,
    revision,
    command_id: canonicalText(data.command_id, "scene_event.command_id"),
  };
  if (eventType === "created" || eventType === "imported") {
    return {
      ...common,
      event_type: eventType,
      scene: parseSceneRecord(data.scene, "scene_event.scene"),
      became_active: booleanValue(
        data.became_active,
        "scene_event.became_active",
      ),
    };
  }
  if (eventType === "duplicated") {
    return {
      ...common,
      event_type: "duplicated",
      source_scene_id: canonicalText(
        data.source_scene_id,
        "scene_event.source_scene_id",
      ),
      scene: parseSceneRecord(data.scene, "scene_event.scene"),
      became_active: booleanValue(
        data.became_active,
        "scene_event.became_active",
      ),
    };
  }
  if (eventType === "activated") {
    return {
      ...common,
      event_type: "activated",
      scene_id: canonicalText(data.scene_id, "scene_event.scene_id"),
      previous_scene_id: canonicalText(
        data.previous_scene_id,
        "scene_event.previous_scene_id",
      ),
    };
  }
  return {
    ...common,
    event_type: "archived",
    scene_id: canonicalText(data.scene_id, "scene_event.scene_id"),
    successor_scene_id:
      data.successor_scene_id === null
        ? null
        : canonicalText(
            data.successor_scene_id,
            "scene_event.successor_scene_id",
          ),
    active_scene_id: canonicalText(
      data.active_scene_id,
      "scene_event.active_scene_id",
    ),
  };
}

export function parseSceneLibraryResponse(value: unknown): SceneLibraryResponse {
  const data = exactObject(
    value,
    [
      "schema_version",
      "session_id",
      "table_id",
      "command_id",
      "revision",
      "replayed",
      "event",
    ],
    "scene_library_response",
  );
  const event = parseSceneEvent(data.event);
  const tableId = canonicalText(data.table_id, "scene_library_response.table_id");
  const commandId = canonicalText(
    data.command_id,
    "scene_library_response.command_id",
  );
  const revision = integer(data.revision, "scene_library_response.revision", 1);
  if (
    event.table_id !== tableId ||
    event.command_id !== commandId ||
    event.revision !== revision
  ) {
    throw new Error("scene_library_response event must match its receipt");
  }
  return {
    schema_version: literal(
      data.schema_version,
      ["vtt.scene_library_response.v1"],
      "scene_library_response.schema_version",
    ),
    session_id: canonicalText(
      data.session_id,
      "scene_library_response.session_id",
    ),
    table_id: tableId,
    command_id: commandId,
    revision,
    replayed: booleanValue(data.replayed, "scene_library_response.replayed"),
    event,
  };
}

function jsonObject(value: unknown, path: string): Record<string, JsonValue> {
  return objectValue(value, path) as Record<string, JsonValue>;
}

async function sceneResponseJson(response: Response): Promise<unknown> {
  let value: unknown;
  try {
    value = await response.json();
  } catch {
    throw new VttApiError("The scene service returned unreadable data.", {
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
    literal(error.schema_version, ["vtt.error.v1"], "error.schema_version");
    throw new VttApiError(canonicalText(error.message, "error.message", 10_000), {
      code: canonicalText(error.code, "error.code"),
      status: response.status,
      details: jsonObject(error.details, "error.details"),
    });
  } catch (error) {
    if (error instanceof VttApiError) throw error;
    throw new VttApiError("The scene service rejected the request.", {
      code: "http_error",
      status: response.status,
    });
  }
}

export async function getSceneLibraryView(
  signal?: AbortSignal,
  bearerToken?: string | null,
): Promise<SceneLibraryView> {
  const response = await fetch(`${VTT_API_BASE_URL}/api/v1/scenes`, {
    method: "GET",
    headers: buildVttRequestHeaders({
      accept: "application/json",
      bearerToken,
    }),
    signal,
  });
  return parseSceneLibraryView(await sceneResponseJson(response));
}

export async function postSceneLibraryRequest(
  payload: SceneLibraryRequest,
  signal?: AbortSignal,
  bearerToken?: string | null,
): Promise<SceneLibraryResponse> {
  const response = await fetch(`${VTT_API_BASE_URL}/api/v1/scene-commands`, {
    method: "POST",
    headers: buildVttRequestHeaders({
      accept: "application/json",
      bearerToken,
      contentType: "application/json",
    }),
    body: JSON.stringify(payload),
    signal,
  });
  return parseSceneLibraryResponse(await sceneResponseJson(response));
}

export function sceneEventsUrl(after: number): string {
  if (!Number.isSafeInteger(after) || after < 0) {
    throw new Error("Scene event cursor must be a non-negative safe integer");
  }
  return `${VTT_API_BASE_URL}/api/v1/scene-events?after=${after}`;
}

export function parseSceneSseBlock(block: string): SceneEvent | null {
  if (typeof block !== "string") throw new Error("Scene SSE block must be text");
  const fields = new Map<string, string>();
  for (const rawLine of block.replaceAll("\r\n", "\n").split("\n")) {
    if (!rawLine || rawLine.startsWith(":")) continue;
    const separator = rawLine.indexOf(":");
    if (separator <= 0) throw new Error("Scene SSE contains a malformed field");
    const name = rawLine.slice(0, separator);
    const fieldValue = rawLine.slice(separator + 1).replace(/^ /, "");
    if (!new Set(["id", "event", "data"]).has(name) || fields.has(name)) {
      throw new Error("Scene SSE contains duplicate or unsupported fields");
    }
    fields.set(name, fieldValue);
  }
  if (fields.size === 0) return null;
  if (fields.get("event") !== "vtt.scene_event") {
    throw new Error("Scene SSE event type is invalid");
  }
  const idText = fields.get("id");
  const dataText = fields.get("data");
  if (!idText || !dataText || !/^\d+$/.test(idText)) {
    throw new Error("Scene SSE id must be a canonical integer");
  }
  const id = Number(idText);
  if (!Number.isSafeInteger(id) || String(id) !== idText) {
    throw new Error("Scene SSE id must be a canonical safe integer");
  }
  let decoded: unknown;
  try {
    decoded = JSON.parse(dataText);
  } catch {
    throw new Error("Scene SSE data must be valid JSON");
  }
  const event = parseSceneEvent(decoded);
  if (id !== event.sequence) {
    throw new Error("Scene SSE id must match the event sequence");
  }
  return event;
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

export async function streamSceneEvents(input: {
  after: number;
  bearerToken?: string | null;
  signal: AbortSignal;
  onEvent: (event: SceneEvent) => void;
  onOpen?: () => void;
}): Promise<number> {
  let cursor = integer(input.after, "after");
  const response = await fetch(sceneEventsUrl(cursor), {
    method: "GET",
    headers: buildVttRequestHeaders({
      accept: "text/event-stream",
      bearerToken: input.bearerToken,
    }),
    signal: input.signal,
  });
  if (!response.ok) await sceneResponseJson(response);
  if (!response.body) {
    throw new VttApiError("The scene event stream has no response body.", {
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
      const event = parseSceneSseBlock(buffer.slice(0, boundary.index));
      buffer = buffer.slice(boundary.index + boundary.length);
      if (event && event.sequence > cursor) {
        cursor = event.sequence;
        input.onEvent(event);
      }
      boundary = findSseBoundary(buffer);
    }
    if (done) break;
  }
  if (buffer.trim() !== "") {
    throw new Error("Scene SSE ended with an incomplete event");
  }
  return cursor;
}
