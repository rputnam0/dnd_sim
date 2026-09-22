import {
  VTT_API_BASE_URL,
  VttApiError,
  type JsonValue,
} from "./vtt-client";
import {
  parseSceneMapAssetReference,
  type SceneMapAssetReference,
} from "./vtt-scenes";
import { buildVttRequestHeaders } from "./vtt-transport";

export interface MapAssetRecord {
  schema_version: "vtt.map_asset_record.v1";
  reference: SceneMapAssetReference;
  width_px: number;
  height_px: number;
  byte_size: number;
}

export interface MapAssetCatalog {
  schema_version: "vtt.map_asset_catalog.v1";
  table_id: string;
  revision: number;
  assets: MapAssetRecord[];
}

export interface MapAssetUploadRequest {
  schema_version: "vtt.map_asset_upload_request.v1";
  session_id: string;
  command: {
    schema_version: "vtt.map_asset_upload_command.v1";
    table_id: string;
    command_id: string;
    expected_revision: number;
    asset_id: string;
    alt_text: string;
    content_base64: string;
  };
}

export interface MapAssetUploadResponse {
  schema_version: "vtt.map_asset_upload_response.v1";
  session_id: string;
  table_id: string;
  command_id: string;
  revision: number;
  replayed: boolean;
  asset: MapAssetRecord;
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
  const data = objectValue(value, path);
  const expected = new Set(keys);
  for (const key of Object.keys(data)) {
    if (!expected.has(key)) throw new Error(`${path} contains unexpected field "${key}"`);
  }
  for (const key of keys) {
    if (!(key in data)) throw new Error(`${path} is missing field "${key}"`);
  }
  return data;
}

function canonicalText(value: unknown, path: string, maximum = 240): string {
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

function integer(value: unknown, path: string, minimum = 0): number {
  if (
    typeof value !== "number" ||
    !Number.isSafeInteger(value) ||
    value < minimum
  ) {
    throw new Error(`${path} must be a safe integer >= ${minimum}`);
  }
  return value;
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

function booleanValue(value: unknown, path: string): boolean {
  if (typeof value !== "boolean") throw new Error(`${path} must be a boolean`);
  return value;
}

function compareCodePoints(left: string, right: string): number {
  const leftPoints = Array.from(left, (value) => value.codePointAt(0) as number);
  const rightPoints = Array.from(right, (value) => value.codePointAt(0) as number);
  for (let index = 0; index < Math.min(leftPoints.length, rightPoints.length); index += 1) {
    if (leftPoints[index] !== rightPoints[index]) return leftPoints[index] - rightPoints[index];
  }
  return leftPoints.length - rightPoints.length;
}

function parseMapAssetRecord(value: unknown, path: string): MapAssetRecord {
  const data = exactObject(
    value,
    ["schema_version", "reference", "width_px", "height_px", "byte_size"],
    path,
  );
  return {
    schema_version: literal(
      data.schema_version,
      ["vtt.map_asset_record.v1"],
      `${path}.schema_version`,
    ),
    reference: parseSceneMapAssetReference(data.reference, `${path}.reference`),
    width_px: integer(data.width_px, `${path}.width_px`, 1),
    height_px: integer(data.height_px, `${path}.height_px`, 1),
    byte_size: integer(data.byte_size, `${path}.byte_size`, 1),
  };
}

export function parseMapAssetCatalog(value: unknown): MapAssetCatalog {
  const data = exactObject(
    value,
    ["schema_version", "table_id", "revision", "assets"],
    "map_asset_catalog",
  );
  if (!Array.isArray(data.assets)) {
    throw new Error("map_asset_catalog.assets must be an ordered list");
  }
  const assets = data.assets.map((asset, index) =>
    parseMapAssetRecord(asset, `map_asset_catalog.assets[${index}]`),
  );
  const assetIds = assets.map((asset) => asset.reference.asset_id);
  if (
    new Set(assetIds).size !== assetIds.length ||
    assetIds.some(
      (assetId, index) =>
        index > 0 && compareCodePoints(assetIds[index - 1], assetId) > 0,
    )
  ) {
    throw new Error("map_asset_catalog assets must have unique sorted asset IDs");
  }
  return {
    schema_version: literal(
      data.schema_version,
      ["vtt.map_asset_catalog.v1"],
      "map_asset_catalog.schema_version",
    ),
    table_id: canonicalText(data.table_id, "map_asset_catalog.table_id", 128),
    revision: integer(data.revision, "map_asset_catalog.revision"),
    assets,
  };
}

export function parseMapAssetUploadResponse(
  value: unknown,
): MapAssetUploadResponse {
  const data = exactObject(
    value,
    [
      "schema_version",
      "session_id",
      "table_id",
      "command_id",
      "revision",
      "replayed",
      "asset",
    ],
    "map_asset_upload_response",
  );
  return {
    schema_version: literal(
      data.schema_version,
      ["vtt.map_asset_upload_response.v1"],
      "map_asset_upload_response.schema_version",
    ),
    session_id: canonicalText(data.session_id, "map_asset_upload_response.session_id"),
    table_id: canonicalText(data.table_id, "map_asset_upload_response.table_id"),
    command_id: canonicalText(data.command_id, "map_asset_upload_response.command_id"),
    revision: integer(data.revision, "map_asset_upload_response.revision", 1),
    replayed: booleanValue(data.replayed, "map_asset_upload_response.replayed"),
    asset: parseMapAssetRecord(data.asset, "map_asset_upload_response.asset"),
  };
}

export function buildMapAssetUploadRequest(input: {
  sessionId: string;
  tableId: string;
  commandId?: string;
  expectedRevision: number;
  assetId: string;
  altText: string;
  contentBase64: string;
}): MapAssetUploadRequest {
  const assetId = canonicalText(input.assetId, "assetId", 128);
  if (!/^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/.test(assetId)) {
    throw new Error("assetId must be a URL-safe identifier");
  }
  const contentBase64 = canonicalText(
    input.contentBase64,
    "contentBase64",
    16_777_216,
  );
  if (!/^[A-Za-z0-9+/]+={0,2}$/.test(contentBase64)) {
    throw new Error("contentBase64 must be canonical base64");
  }
  return {
    schema_version: "vtt.map_asset_upload_request.v1",
    session_id: canonicalText(input.sessionId, "sessionId", 128),
    command: {
      schema_version: "vtt.map_asset_upload_command.v1",
      table_id: canonicalText(input.tableId, "tableId", 128),
      command_id: canonicalText(input.commandId ?? crypto.randomUUID(), "commandId", 128),
      expected_revision: integer(input.expectedRevision, "expectedRevision"),
      asset_id: assetId,
      alt_text: canonicalText(input.altText, "altText", 240),
      content_base64: contentBase64,
    },
  };
}

export async function blobToBase64(blob: Blob): Promise<string> {
  const bytes = new Uint8Array(await blob.arrayBuffer());
  let binary = "";
  const chunkSize = 32_768;
  for (let offset = 0; offset < bytes.length; offset += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + chunkSize));
  }
  return btoa(binary);
}

async function responseJson(response: Response): Promise<unknown> {
  let value: unknown;
  try {
    value = await response.json();
  } catch {
    throw new VttApiError("The map asset service returned unreadable data.", {
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
    throw new VttApiError(canonicalText(error.message, "error.message"), {
      code: canonicalText(error.code, "error.code"),
      status: response.status,
      details: objectValue(error.details, "error.details") as Record<string, JsonValue>,
    });
  } catch (error) {
    if (error instanceof VttApiError) throw error;
    throw new VttApiError("The map asset service rejected the request.", {
      code: "http_error",
      status: response.status,
    });
  }
}

export async function getMapAssetCatalog(
  signal?: AbortSignal,
  bearerToken?: string | null,
  apiBaseUrl = VTT_API_BASE_URL,
): Promise<MapAssetCatalog> {
  const response = await fetch(`${apiBaseUrl.replace(/\/+$/, "")}/api/v1/map-assets`, {
    method: "GET",
    headers: buildVttRequestHeaders({
      accept: "application/json",
      bearerToken,
    }),
    signal,
    credentials: "omit", redirect: "error", cache: "no-store",
  });
  return parseMapAssetCatalog(await responseJson(response));
}

export async function postMapAssetUpload(
  request: MapAssetUploadRequest,
  signal?: AbortSignal,
  bearerToken?: string | null,
  apiBaseUrl = VTT_API_BASE_URL,
): Promise<MapAssetUploadResponse> {
  const response = await fetch(`${apiBaseUrl.replace(/\/+$/, "")}/api/v1/map-assets`, {
    method: "POST",
    headers: buildVttRequestHeaders({
      accept: "application/json",
      contentType: "application/json",
      bearerToken,
    }),
    body: JSON.stringify(request),
    signal,
    credentials: "omit", redirect: "error", cache: "no-store",
  });
  const parsed = parseMapAssetUploadResponse(await responseJson(response));
  if (
    parsed.session_id !== request.session_id ||
    parsed.table_id !== request.command.table_id ||
    parsed.command_id !== request.command.command_id ||
    parsed.asset.reference.asset_id !== request.command.asset_id
  ) {
    throw new Error("The map asset upload response does not match its request");
  }
  return parsed;
}

export async function fetchAuthenticatedMapAsset(
  reference: SceneMapAssetReference,
  bearerToken: string | null,
  signal?: AbortSignal,
  apiBaseUrl = VTT_API_BASE_URL,
): Promise<Blob> {
  const canonical = parseSceneMapAssetReference(reference);
  // References are strict local paths. URL(path, base) would discard both a
  // reverse-proxy prefix and the world mount, risking cross-world requests.
  const response = await fetch(`${apiBaseUrl.replace(/\/+$/, "")}${canonical.content_path}`, {
    method: "GET",
    headers: buildVttRequestHeaders({
      accept: canonical.media_type,
      bearerToken,
    }),
    signal,
    credentials: "omit", redirect: "error", cache: "no-store",
  });
  if (!response.ok) {
    await responseJson(response);
    throw new Error("unreachable");
  }
  const contentType = response.headers.get("content-type")?.split(";", 1)[0];
  if (contentType !== canonical.media_type) {
    throw new Error("Map asset content type does not match its reference");
  }
  const bytes = await response.arrayBuffer();
  const digestBytes = new Uint8Array(await crypto.subtle.digest("SHA-256", bytes));
  const digest = Array.from(digestBytes, (value) => value.toString(16).padStart(2, "0")).join("");
  if (digest !== canonical.sha256) {
    throw new Error("Map asset digest does not match its reference");
  }
  return new Blob([bytes], { type: canonical.media_type });
}
