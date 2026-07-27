import {
  VTT_API_BASE_URL,
  VttApiError,
  type JsonValue,
  type Position3,
} from "./vtt-client";

export interface AnnotationPoint {
  x_ft: number;
  y_ft: number;
  z_ft: number;
}

interface AnnotationBase {
  schema_version: "vtt.annotation.v1";
  annotation_id: string;
  scene_id: string;
  author_id: string;
  audience: string[];
}

export interface PingAnnotation extends AnnotationBase {
  annotation_type: "ping";
  position: AnnotationPoint;
  duration_ms: number;
}

export interface RulerAnnotation extends AnnotationBase {
  annotation_type: "ruler";
  waypoints: AnnotationPoint[];
  segment_distances_ft: number[];
  total_distance_ft: number;
}

export interface CircleTemplateAnnotation extends AnnotationBase {
  annotation_type: "circle_template";
  center: AnnotationPoint;
  radius_ft: number;
}

export interface ConeTemplateAnnotation extends AnnotationBase {
  annotation_type: "cone_template";
  origin: AnnotationPoint;
  direction_degrees: number;
  length_ft: number;
  angle_degrees: number;
}

export interface LineTemplateAnnotation extends AnnotationBase {
  annotation_type: "line_template";
  start: AnnotationPoint;
  end: AnnotationPoint;
  width_ft: number;
}

export interface CubeTemplateAnnotation extends AnnotationBase {
  annotation_type: "cube_template";
  center: AnnotationPoint;
  size_ft: number;
}

export type VttAnnotation =
  | PingAnnotation
  | RulerAnnotation
  | CircleTemplateAnnotation
  | ConeTemplateAnnotation
  | LineTemplateAnnotation
  | CubeTemplateAnnotation;

export interface AnnotationsView {
  schema_version: "vtt.annotations_view.v1";
  session_id: string;
  table_id: string;
  scene_id: string;
  revision: number;
  annotations: VttAnnotation[];
}

export interface AnnotationPutCommand {
  schema_version: "vtt.annotation_command.v1";
  table_id: string;
  command_id: string;
  expected_revision: number;
  command_type: "put";
  annotation: VttAnnotation;
}

export interface AnnotationPutRequest {
  schema_version: "vtt.annotation_request.v1";
  session_id: string;
  command: AnnotationPutCommand;
}

interface AnnotationEventBase {
  schema_version: "vtt.annotation_event.v1";
  table_id: string;
  event_id: string;
  sequence: number;
  revision: number;
  command_id: string;
  annotation_id: string;
}

export interface AnnotationPutEvent extends AnnotationEventBase {
  event_type: "put";
  annotation: VttAnnotation;
}

export interface AnnotationDeleteEvent extends AnnotationEventBase {
  event_type: "delete";
  scene_id: string;
  audience: string[];
}

export type AnnotationEvent = AnnotationPutEvent | AnnotationDeleteEvent;

export interface AnnotationReceipt {
  schema_version: "vtt.annotation_receipt.v1";
  table_id: string;
  command_id: string;
  revision: number;
  event: AnnotationEvent;
}

export interface AnnotationResponse {
  schema_version: "vtt.annotation_response.v1";
  session_id: string;
  replayed: boolean;
  receipt: AnnotationReceipt;
}

type ObjectValue = Record<string, unknown>;

const MAX_ABSOLUTE_COORDINATE_FT = 1_000_000;
const MAX_TEMPLATE_SIZE_FT = 100_000;
const MAX_RULER_WAYPOINTS = 128;
const MAX_PING_DURATION_MS = 60_000;

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
    if (!(key in result)) {
      throw new Error(`${path} is missing field "${key}"`);
    }
  }
  return result;
}

function canonicalText(value: unknown, path: string, maximum = 128): string {
  if (
    typeof value !== "string" ||
    value.length === 0 ||
    Array.from(value).length > maximum ||
    value.trim() !== value
  ) {
    throw new Error(`${path} must be canonical non-empty text`);
  }
  return value;
}

function compareUnicodeCodePoints(left: string, right: string): number {
  const leftPoints = Array.from(left, (character) =>
    character.codePointAt(0) as number,
  );
  const rightPoints = Array.from(right, (character) =>
    character.codePointAt(0) as number,
  );
  const sharedLength = Math.min(leftPoints.length, rightPoints.length);
  for (let index = 0; index < sharedLength; index += 1) {
    if (leftPoints[index] !== rightPoints[index]) {
      return leftPoints[index] - rightPoints[index];
    }
  }
  return leftPoints.length - rightPoints.length;
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

function finiteNumber(value: unknown, path: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new Error(`${path} must be a finite number`);
  }
  return value;
}

function boundedNumber(
  value: unknown,
  path: string,
  minimum: number,
  maximum: number,
  minimumInclusive = true,
  maximumInclusive = true,
): number {
  const result = finiteNumber(value, path);
  if (
    (minimumInclusive ? result < minimum : result <= minimum) ||
    (maximumInclusive ? result > maximum : result >= maximum)
  ) {
    throw new Error(`${path} is outside the supported range`);
  }
  return result;
}

function integerValue(value: unknown, path: string, minimum = 0): number {
  const result = finiteNumber(value, path);
  if (!Number.isSafeInteger(result) || result < minimum) {
    throw new Error(`${path} must be a safe integer >= ${minimum}`);
  }
  return result;
}

function booleanValue(value: unknown, path: string): boolean {
  if (typeof value !== "boolean") {
    throw new Error(`${path} must be a boolean`);
  }
  return value;
}

function parseAudience(value: unknown, path: string): string[] {
  if (!Array.isArray(value) || value.length === 0) {
    throw new Error(`${path} must be a non-empty ordered list`);
  }
  const audience = value.map((recipient, index) =>
    canonicalText(recipient, `${path}[${index}]`),
  );
  if (new Set(audience).size !== audience.length) {
    throw new Error(`${path} must contain unique recipients`);
  }
  if (audience.includes("all") && (audience.length !== 1 || audience[0] !== "all")) {
    throw new Error(`${path} recipient all cannot be combined with other recipients`);
  }
  return audience;
}

function parsePoint(value: unknown, path: string): AnnotationPoint {
  const data = exactObject(value, ["x_ft", "y_ft", "z_ft"], path);
  return {
    x_ft: boundedNumber(
      data.x_ft,
      `${path}.x_ft`,
      -MAX_ABSOLUTE_COORDINATE_FT,
      MAX_ABSOLUTE_COORDINATE_FT,
    ),
    y_ft: boundedNumber(
      data.y_ft,
      `${path}.y_ft`,
      -MAX_ABSOLUTE_COORDINATE_FT,
      MAX_ABSOLUTE_COORDINATE_FT,
    ),
    z_ft: boundedNumber(
      data.z_ft,
      `${path}.z_ft`,
      -MAX_ABSOLUTE_COORDINATE_FT,
      MAX_ABSOLUTE_COORDINATE_FT,
    ),
  };
}

function parseAnnotationBase(
  data: ObjectValue,
  path: string,
): AnnotationBase {
  return {
    schema_version: literalValue(
      data.schema_version,
      ["vtt.annotation.v1"],
      `${path}.schema_version`,
    ),
    annotation_id: canonicalText(data.annotation_id, `${path}.annotation_id`),
    scene_id: canonicalText(data.scene_id, `${path}.scene_id`),
    author_id: canonicalText(data.author_id, `${path}.author_id`),
    audience: parseAudience(data.audience, `${path}.audience`),
  };
}

function parseAnnotation(value: unknown, path: string): VttAnnotation {
  const raw = objectValue(value, path);
  const annotationType = literalValue(
    raw.annotation_type,
    [
      "ping",
      "ruler",
      "circle_template",
      "cone_template",
      "line_template",
      "cube_template",
    ],
    `${path}.annotation_type`,
  );
  const baseKeys = [
    "schema_version",
    "annotation_id",
    "scene_id",
    "author_id",
    "audience",
    "annotation_type",
  ];
  if (annotationType === "ping") {
    const data = exactObject(
      raw,
      [...baseKeys, "position", "duration_ms"],
      path,
    );
    const duration = integerValue(data.duration_ms, `${path}.duration_ms`, 250);
    if (duration > MAX_PING_DURATION_MS) {
      throw new Error(`${path}.duration_ms exceeds the supported maximum`);
    }
    return {
      ...parseAnnotationBase(data, path),
      annotation_type: "ping",
      position: parsePoint(data.position, `${path}.position`),
      duration_ms: duration,
    };
  }
  if (annotationType === "ruler") {
    const data = exactObject(
      raw,
      [
        ...baseKeys,
        "waypoints",
        "segment_distances_ft",
        "total_distance_ft",
      ],
      path,
    );
    if (
      !Array.isArray(data.waypoints) ||
      data.waypoints.length < 2 ||
      data.waypoints.length > MAX_RULER_WAYPOINTS
    ) {
      throw new Error(`${path}.waypoints must contain 2-${MAX_RULER_WAYPOINTS} points`);
    }
    const waypoints = data.waypoints.map((point, index) =>
      parsePoint(point, `${path}.waypoints[${index}]`),
    );
    if (!Array.isArray(data.segment_distances_ft)) {
      throw new Error(`${path}.segment_distances_ft must be an array`);
    }
    const expectedSegments = waypoints.slice(1).map((end, index) => {
      const start = waypoints[index];
      if (
        start.x_ft === end.x_ft &&
        start.y_ft === end.y_ft &&
        start.z_ft === end.z_ft
      ) {
        throw new Error(`${path}.waypoints must not repeat consecutively`);
      }
      return Math.max(
        Math.abs(end.x_ft - start.x_ft),
        Math.abs(end.y_ft - start.y_ft),
        Math.abs(end.z_ft - start.z_ft),
      );
    });
    const segments = data.segment_distances_ft.map((distance, index) =>
      boundedNumber(
        distance,
        `${path}.segment_distances_ft[${index}]`,
        0,
        MAX_ABSOLUTE_COORDINATE_FT * 2,
      ),
    );
    if (
      segments.length !== expectedSegments.length ||
      segments.some((distance, index) => distance !== expectedSegments[index])
    ) {
      throw new Error(`${path}.segment_distances_ft must match waypoints`);
    }
    const total = boundedNumber(
      data.total_distance_ft,
      `${path}.total_distance_ft`,
      0,
      MAX_ABSOLUTE_COORDINATE_FT * 2 * (MAX_RULER_WAYPOINTS - 1),
    );
    if (total !== segments.reduce((sum, distance) => sum + distance, 0)) {
      throw new Error(`${path}.total_distance_ft must match segment distances`);
    }
    return {
      ...parseAnnotationBase(data, path),
      annotation_type: "ruler",
      waypoints,
      segment_distances_ft: segments,
      total_distance_ft: total,
    };
  }
  if (annotationType === "circle_template") {
    const data = exactObject(raw, [...baseKeys, "center", "radius_ft"], path);
    return {
      ...parseAnnotationBase(data, path),
      annotation_type: "circle_template",
      center: parsePoint(data.center, `${path}.center`),
      radius_ft: boundedNumber(
        data.radius_ft,
        `${path}.radius_ft`,
        0,
        MAX_TEMPLATE_SIZE_FT,
        false,
      ),
    };
  }
  if (annotationType === "cone_template") {
    const data = exactObject(
      raw,
      [
        ...baseKeys,
        "origin",
        "direction_degrees",
        "length_ft",
        "angle_degrees",
      ],
      path,
    );
    return {
      ...parseAnnotationBase(data, path),
      annotation_type: "cone_template",
      origin: parsePoint(data.origin, `${path}.origin`),
      direction_degrees: boundedNumber(
        data.direction_degrees,
        `${path}.direction_degrees`,
        0,
        360,
        true,
        false,
      ),
      length_ft: boundedNumber(
        data.length_ft,
        `${path}.length_ft`,
        0,
        MAX_TEMPLATE_SIZE_FT,
        false,
      ),
      angle_degrees: boundedNumber(
        data.angle_degrees,
        `${path}.angle_degrees`,
        0,
        180,
        false,
      ),
    };
  }
  if (annotationType === "line_template") {
    const data = exactObject(raw, [...baseKeys, "start", "end", "width_ft"], path);
    const start = parsePoint(data.start, `${path}.start`);
    const end = parsePoint(data.end, `${path}.end`);
    if (start.z_ft !== end.z_ft) {
      throw new Error(`${path} line endpoints must share z_ft`);
    }
    if (start.x_ft === end.x_ft && start.y_ft === end.y_ft) {
      throw new Error(`${path} line endpoints must be horizontally distinct`);
    }
    return {
      ...parseAnnotationBase(data, path),
      annotation_type: "line_template",
      start,
      end,
      width_ft: boundedNumber(
        data.width_ft,
        `${path}.width_ft`,
        0,
        MAX_TEMPLATE_SIZE_FT,
        false,
      ),
    };
  }
  const data = exactObject(raw, [...baseKeys, "center", "size_ft"], path);
  return {
    ...parseAnnotationBase(data, path),
    annotation_type: "cube_template",
    center: parsePoint(data.center, `${path}.center`),
    size_ft: boundedNumber(
      data.size_ft,
      `${path}.size_ft`,
      0,
      MAX_TEMPLATE_SIZE_FT,
      false,
    ),
  };
}

export function parseAnnotationsView(value: unknown): AnnotationsView {
  const data = exactObject(
    value,
    [
      "schema_version",
      "session_id",
      "table_id",
      "scene_id",
      "revision",
      "annotations",
    ],
    "annotations_view",
  );
  if (!Array.isArray(data.annotations)) {
    throw new Error("annotations_view.annotations must be an array");
  }
  const sceneId = canonicalText(data.scene_id, "annotations_view.scene_id");
  const annotations = data.annotations.map((annotation, index) =>
    parseAnnotation(annotation, `annotations_view.annotations[${index}]`),
  );
  const ids = annotations.map((annotation) => annotation.annotation_id);
  if (new Set(ids).size !== ids.length) {
    throw new Error("annotations_view.annotations must have unique annotation IDs");
  }
  if (
    ids.some(
      (id, index) =>
        index > 0 && compareUnicodeCodePoints(id, ids[index - 1]) < 0,
    )
  ) {
    throw new Error("annotations_view.annotations must use sorted annotation-ID order");
  }
  if (annotations.some((annotation) => annotation.scene_id !== sceneId)) {
    throw new Error("annotation scene_id must match the annotations view scene_id");
  }
  return {
    schema_version: literalValue(
      data.schema_version,
      ["vtt.annotations_view.v1"],
      "annotations_view.schema_version",
    ),
    session_id: canonicalText(data.session_id, "annotations_view.session_id"),
    table_id: canonicalText(data.table_id, "annotations_view.table_id"),
    scene_id: sceneId,
    revision: integerValue(data.revision, "annotations_view.revision"),
    annotations,
  };
}

export function parseAnnotationEvent(value: unknown): AnnotationEvent {
  const raw = objectValue(value, "annotation_event");
  const eventType = literalValue(
    raw.event_type,
    ["put", "delete"],
    "annotation_event.event_type",
  );
  const commonKeys = [
    "schema_version",
    "table_id",
    "event_id",
    "sequence",
    "revision",
    "command_id",
    "annotation_id",
    "event_type",
  ];
  const data = exactObject(
    raw,
    eventType === "put"
      ? [...commonKeys, "annotation"]
      : [...commonKeys, "scene_id", "audience"],
    "annotation_event",
  );
  const common = {
    schema_version: literalValue(
      data.schema_version,
      ["vtt.annotation_event.v1"],
      "annotation_event.schema_version",
    ),
    table_id: canonicalText(data.table_id, "annotation_event.table_id"),
    event_id: canonicalText(data.event_id, "annotation_event.event_id", 512),
    sequence: integerValue(data.sequence, "annotation_event.sequence", 1),
    revision: integerValue(data.revision, "annotation_event.revision", 1),
    command_id: canonicalText(data.command_id, "annotation_event.command_id"),
    annotation_id: canonicalText(
      data.annotation_id,
      "annotation_event.annotation_id",
    ),
  };
  if (common.sequence !== common.revision) {
    throw new Error("annotation_event sequence must match revision");
  }
  if (eventType === "put") {
    const annotation = parseAnnotation(data.annotation, "annotation_event.annotation");
    if (annotation.annotation_id !== common.annotation_id) {
      throw new Error(
        "annotation_event.annotation.annotation_id must match annotation_id",
      );
    }
    return { ...common, event_type: "put", annotation };
  }
  return {
    ...common,
    event_type: "delete",
    scene_id: canonicalText(data.scene_id, "annotation_event.scene_id"),
    audience: parseAudience(data.audience, "annotation_event.audience"),
  };
}

export function parseAnnotationResponse(value: unknown): AnnotationResponse {
  const data = exactObject(
    value,
    ["schema_version", "session_id", "replayed", "receipt"],
    "annotation_response",
  );
  const receiptData = exactObject(
    data.receipt,
    ["schema_version", "table_id", "command_id", "revision", "event"],
    "annotation_response.receipt",
  );
  const event = parseAnnotationEvent(receiptData.event);
  const tableId = canonicalText(
    receiptData.table_id,
    "annotation_response.receipt.table_id",
  );
  const commandId = canonicalText(
    receiptData.command_id,
    "annotation_response.receipt.command_id",
  );
  const revision = integerValue(
    receiptData.revision,
    "annotation_response.receipt.revision",
    1,
  );
  if (event.table_id !== tableId) {
    throw new Error("receipt event table_id must match receipt table_id");
  }
  if (event.command_id !== commandId) {
    throw new Error("receipt event command_id must match receipt command_id");
  }
  if (event.revision !== revision) {
    throw new Error("receipt event revision must match receipt revision");
  }
  return {
    schema_version: literalValue(
      data.schema_version,
      ["vtt.annotation_response.v1"],
      "annotation_response.schema_version",
    ),
    session_id: canonicalText(
      data.session_id,
      "annotation_response.session_id",
    ),
    replayed: booleanValue(data.replayed, "annotation_response.replayed"),
    receipt: {
      schema_version: literalValue(
        receiptData.schema_version,
        ["vtt.annotation_receipt.v1"],
        "annotation_response.receipt.schema_version",
      ),
      table_id: tableId,
      command_id: commandId,
      revision,
      event,
    },
  };
}

function requireText(value: string, field: string): string {
  return canonicalText(value, field);
}

function requirePosition(value: Position3): Position3 {
  if (!Array.isArray(value) || value.length !== 3) {
    throw new Error("position must contain exactly three coordinates");
  }
  return [
    boundedNumber(
      value[0],
      "position[0]",
      -MAX_ABSOLUTE_COORDINATE_FT,
      MAX_ABSOLUTE_COORDINATE_FT,
    ),
    boundedNumber(
      value[1],
      "position[1]",
      -MAX_ABSOLUTE_COORDINATE_FT,
      MAX_ABSOLUTE_COORDINATE_FT,
    ),
    boundedNumber(
      value[2],
      "position[2]",
      -MAX_ABSOLUTE_COORDINATE_FT,
      MAX_ABSOLUTE_COORDINATE_FT,
    ),
  ];
}

export function buildPingPutRequest(input: {
  sessionId: string;
  tableId: string;
  sceneId: string;
  authorId: string;
  expectedRevision: number;
  position: Position3;
  commandId?: string;
  annotationId?: string;
  durationMs?: number;
}): AnnotationPutRequest {
  const position = requirePosition(input.position);
  const duration = integerValue(input.durationMs ?? 1_500, "durationMs", 250);
  if (duration > MAX_PING_DURATION_MS) {
    throw new Error("durationMs exceeds the supported maximum");
  }
  return {
    schema_version: "vtt.annotation_request.v1",
    session_id: requireText(input.sessionId, "sessionId"),
    command: {
      schema_version: "vtt.annotation_command.v1",
      table_id: requireText(input.tableId, "tableId"),
      command_id: requireText(input.commandId ?? crypto.randomUUID(), "commandId"),
      expected_revision: integerValue(
        input.expectedRevision,
        "expectedRevision",
      ),
      command_type: "put",
      annotation: {
        schema_version: "vtt.annotation.v1",
        annotation_id: requireText(
          input.annotationId ?? crypto.randomUUID(),
          "annotationId",
        ),
        scene_id: requireText(input.sceneId, "sceneId"),
        author_id: requireText(input.authorId, "authorId"),
        audience: ["all"],
        annotation_type: "ping",
        position: {
          x_ft: position[0],
          y_ft: position[1],
          z_ft: position[2],
        },
        duration_ms: duration,
      },
    },
  };
}

export function applyAnnotationEvent(
  view: AnnotationsView,
  event: AnnotationEvent,
): AnnotationsView {
  if (event.table_id !== view.table_id) {
    throw new Error("annotation event table_id does not match the hydrated view");
  }
  const eventSceneId =
    event.event_type === "put" ? event.annotation.scene_id : event.scene_id;
  if (eventSceneId !== view.scene_id) {
    throw new Error("annotation event scene_id does not match the hydrated view");
  }
  if (event.revision <= view.revision) return view;
  const annotations = new Map(
    view.annotations.map((annotation) => [annotation.annotation_id, annotation]),
  );
  if (event.event_type === "put") {
    annotations.set(event.annotation_id, event.annotation);
  } else {
    annotations.delete(event.annotation_id);
  }
  return {
    ...view,
    revision: event.revision,
    annotations: [...annotations.values()].sort((left, right) =>
      compareUnicodeCodePoints(left.annotation_id, right.annotation_id),
    ),
  };
}

export function parseAnnotationSseBlock(block: string): AnnotationEvent | null {
  if (typeof block !== "string") {
    throw new Error("annotation SSE block must be text");
  }
  const fields = new Map<string, string>();
  for (const rawLine of block.replaceAll("\r\n", "\n").split("\n")) {
    if (!rawLine || rawLine.startsWith(":")) continue;
    const separator = rawLine.indexOf(":");
    if (separator <= 0) {
      throw new Error("annotation SSE contains a malformed field");
    }
    const name = rawLine.slice(0, separator);
    const value = rawLine.slice(separator + 1).replace(/^ /, "");
    if (!new Set(["id", "event", "data"]).has(name) || fields.has(name)) {
      throw new Error("annotation SSE contains duplicate or unsupported fields");
    }
    fields.set(name, value);
  }
  if (fields.size === 0) return null;
  if (fields.get("event") !== "vtt.annotation_event") {
    throw new Error("annotation SSE event type is invalid");
  }
  const idText = fields.get("id");
  const dataText = fields.get("data");
  if (!idText || !dataText || !/^\d+$/.test(idText) || String(Number(idText)) !== idText) {
    throw new Error("annotation SSE id must be a canonical integer");
  }
  let decoded: unknown;
  try {
    decoded = JSON.parse(dataText);
  } catch {
    throw new Error("annotation SSE data must be valid JSON");
  }
  const event = parseAnnotationEvent(decoded);
  if (Number(idText) !== event.sequence) {
    throw new Error("annotation SSE id must match the event sequence");
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

function jsonObject(value: unknown, path: string): Record<string, JsonValue> {
  const result = objectValue(value, path);
  return result as Record<string, JsonValue>;
}

async function annotationResponseJson(response: Response): Promise<unknown> {
  let value: unknown;
  try {
    value = await response.json();
  } catch {
    throw new VttApiError("The annotation service returned unreadable data.", {
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
    throw new VttApiError("The annotation service rejected the request.", {
      code: "http_error",
      status: response.status,
    });
  }
}

export async function getAnnotationsView(
  signal?: AbortSignal,
): Promise<AnnotationsView> {
  const response = await fetch(`${VTT_API_BASE_URL}/api/v1/annotations`, {
    method: "GET",
    headers: { accept: "application/json" },
    signal,
  });
  return parseAnnotationsView(await annotationResponseJson(response));
}

export async function postAnnotationRequest(
  request: AnnotationPutRequest,
  signal?: AbortSignal,
): Promise<AnnotationResponse> {
  const response = await fetch(
    `${VTT_API_BASE_URL}/api/v1/annotation-commands`,
    {
      method: "POST",
      headers: {
        accept: "application/json",
        "content-type": "application/json",
      },
      body: JSON.stringify(request),
      signal,
    },
  );
  return parseAnnotationResponse(await annotationResponseJson(response));
}

export function vttAnnotationEventsUrl(after: number): string {
  if (!Number.isSafeInteger(after) || after < 0) {
    throw new Error(
      "Annotation event cursor must be a non-negative integer within the safe range",
    );
  }
  return `${VTT_API_BASE_URL}/api/v1/annotation-events?after=${after}`;
}

export async function streamAnnotationEvents(input: {
  after: number;
  signal: AbortSignal;
  onEvent: (event: AnnotationEvent) => void;
  onOpen?: () => void;
}): Promise<number> {
  let cursor = integerValue(input.after, "after");
  const response = await fetch(vttAnnotationEventsUrl(cursor), {
    method: "GET",
    headers: { accept: "text/event-stream" },
    signal: input.signal,
  });
  if (!response.ok) {
    await annotationResponseJson(response);
  }
  if (!response.body) {
    throw new VttApiError("The annotation event stream has no response body.", {
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
      const block = buffer.slice(0, boundary.index);
      buffer = buffer.slice(boundary.index + boundary.length);
      const event = parseAnnotationSseBlock(block);
      if (event && event.sequence > cursor) {
        cursor = event.sequence;
        input.onEvent(event);
      }
      boundary = findSseBoundary(buffer);
    }
    if (done) break;
  }
  if (buffer.trim() !== "") {
    throw new Error("annotation SSE ended with an incomplete event");
  }
  return cursor;
}
