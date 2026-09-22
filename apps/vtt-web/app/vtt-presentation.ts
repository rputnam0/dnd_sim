import { VTT_API_BASE_URL, responseJson, type JsonValue } from "./vtt-client";
import { buildVttRequestHeaders } from "./vtt-transport";

export interface SoundTrack {
  schema_version: "vtt.sound_track.v1";
  track_id: string;
  name: string;
  media_type: "audio/mpeg" | "audio/ogg" | "audio/wav";
  content_path: string;
  sha256: string;
  byte_size: number;
}

export interface SoundPlaylist {
  schema_version: "vtt.sound_playlist.v1";
  playlist_id: string;
  name: string;
  track_ids: string[];
}

export interface SoundPlayback {
  schema_version: "vtt.sound_playback.v1";
  status: "stopped" | "playing" | "paused";
  track_id: string | null;
  playlist_id: string | null;
  position_ms: number;
  loop: boolean;
  audience: string[];
  started_at_ms: number | null;
}

export interface SharedCamera {
  schema_version: "vtt.presentation_camera.v1";
  enabled: boolean;
  epoch: number;
  scene_id: string | null;
  center_x_ft: number | null;
  center_y_ft: number | null;
  zoom: number | null;
}

export interface PresentationView {
  schema_version: "vtt.presentation_view.v1";
  session_id: string;
  table_id: string;
  revision: number;
  server_epoch_ms: number;
  tracks: SoundTrack[];
  playlists: SoundPlaylist[];
  playback: SoundPlayback;
  camera: SharedCamera;
}

export interface PresentationSignal {
  schema_version: "vtt.presentation_signal.v1";
  sequence: number;
  revision: number;
}

export interface PresentationResponse {
  schema_version: "vtt.presentation_response.v1";
  session_id: string;
  replayed: boolean;
  receipt: {
    schema_version: "vtt.presentation_receipt.v1";
    table_id: string;
    command_id: string;
    revision: number;
    signal: PresentationSignal;
  };
}

export type PresentationCommand = Record<string, JsonValue> & {
  schema_version: "vtt.presentation_command.v1";
  command_type: string;
  table_id: string;
  command_id: string;
  expected_revision: number;
};

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
    if (!expected.has(key)) {
      throw new Error(`${path} contains unexpected field ${key}`);
    }
  }
  for (const key of keys) {
    if (!(key in data)) throw new Error(`${path} is missing ${key}`);
  }
  return data;
}

function canonicalText(value: unknown, path: string, maximum = 160): string {
  if (
    typeof value !== "string" ||
    !value ||
    value.trim() !== value ||
    Array.from(value).length > maximum ||
    Array.from(value).some((item) => /\p{Cc}/u.test(item))
  ) {
    throw new Error(`${path} must be canonical text`);
  }
  return value;
}

function safeInteger(value: unknown, path: string, minimum = 0): number {
  if (
    typeof value !== "number" ||
    !Number.isSafeInteger(value) ||
    value < minimum
  ) {
    throw new Error(`${path} must be an integer`);
  }
  return value;
}

function finiteNumber(value: unknown, path: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new Error(`${path} must be finite`);
  }
  return value;
}

function booleanValue(value: unknown, path: string): boolean {
  if (typeof value !== "boolean") throw new Error(`${path} must be boolean`);
  return value;
}

function literal<T extends string>(
  value: unknown,
  allowed: readonly T[],
  path: string,
): T {
  if (typeof value !== "string" || !allowed.includes(value as T)) {
    throw new Error(`${path} is invalid`);
  }
  return value as T;
}

function nullableText(value: unknown, path: string): string | null {
  return value === null ? null : canonicalText(value, path, 128);
}

function nullableInteger(value: unknown, path: string): number | null {
  return value === null ? null : safeInteger(value, path);
}

function nullableFinite(value: unknown, path: string): number | null {
  return value === null ? null : finiteNumber(value, path);
}

function compareCodePoints(left: string, right: string): number {
  const leftPoints = Array.from(left, (value) => value.codePointAt(0)!);
  const rightPoints = Array.from(right, (value) => value.codePointAt(0)!);
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

function parseSoundTrack(value: unknown, path: string): SoundTrack {
  const data = exactObject(
    value,
    [
      "schema_version",
      "track_id",
      "name",
      "media_type",
      "content_path",
      "sha256",
      "byte_size",
    ],
    path,
  );
  const trackId = canonicalText(data.track_id, `${path}.track_id`, 128);
  const mediaType = literal(
    data.media_type,
    ["audio/mpeg", "audio/ogg", "audio/wav"] as const,
    `${path}.media_type`,
  );
  const extension =
    mediaType === "audio/mpeg" ? "mp3" : mediaType === "audio/ogg" ? "ogg" : "wav";
  const contentPath = canonicalText(data.content_path, `${path}.content_path`, 512);
  if (contentPath !== `/api/v1/sound-assets/${trackId}/content.${extension}`) {
    throw new Error(`${path} content identity mismatch`);
  }
  const digest = canonicalText(data.sha256, `${path}.sha256`, 64);
  if (!/^[0-9a-f]{64}$/.test(digest)) {
    throw new Error(`${path}.sha256 is invalid`);
  }
  return {
    schema_version: literal(
      data.schema_version,
      ["vtt.sound_track.v1"] as const,
      `${path}.schema_version`,
    ),
    track_id: trackId,
    name: canonicalText(data.name, `${path}.name`),
    media_type: mediaType,
    content_path: contentPath,
    sha256: digest,
    byte_size: safeInteger(data.byte_size, `${path}.byte_size`, 1),
  };
}

function parseSoundPlaylist(value: unknown, path: string): SoundPlaylist {
  const data = exactObject(
    value,
    ["schema_version", "playlist_id", "name", "track_ids"],
    path,
  );
  if (
    !Array.isArray(data.track_ids) ||
    data.track_ids.length < 1 ||
    data.track_ids.length > 128
  ) {
    throw new Error(`${path}.track_ids is invalid`);
  }
  const trackIds = data.track_ids.map((item, index) =>
    canonicalText(item, `${path}.track_ids[${index}]`, 128),
  );
  if (new Set(trackIds).size !== trackIds.length) {
    throw new Error(`${path}.track_ids must be unique`);
  }
  return {
    schema_version: literal(
      data.schema_version,
      ["vtt.sound_playlist.v1"] as const,
      `${path}.schema_version`,
    ),
    playlist_id: canonicalText(data.playlist_id, `${path}.playlist_id`, 128),
    name: canonicalText(data.name, `${path}.name`),
    track_ids: trackIds,
  };
}

function parsePlayback(value: unknown): SoundPlayback {
  const data = exactObject(
    value,
    [
      "schema_version",
      "status",
      "track_id",
      "playlist_id",
      "position_ms",
      "loop",
      "audience",
      "started_at_ms",
    ],
    "presentation.playback",
  );
  if (!Array.isArray(data.audience)) {
    throw new Error("presentation.playback.audience must be an array");
  }
  const playback: SoundPlayback = {
    schema_version: literal(
      data.schema_version,
      ["vtt.sound_playback.v1"] as const,
      "presentation.playback.schema_version",
    ),
    status: literal(
      data.status,
      ["stopped", "playing", "paused"] as const,
      "presentation.playback.status",
    ),
    track_id: nullableText(data.track_id, "presentation.playback.track_id"),
    playlist_id: nullableText(data.playlist_id, "presentation.playback.playlist_id"),
    position_ms: safeInteger(data.position_ms, "presentation.playback.position_ms"),
    loop: booleanValue(data.loop, "presentation.playback.loop"),
    audience: data.audience.map((item, index) =>
      canonicalText(item, `presentation.playback.audience[${index}]`, 256),
    ),
    started_at_ms: nullableInteger(
      data.started_at_ms,
      "presentation.playback.started_at_ms",
    ),
  };
  const stoppedStateIsInvalid =
    playback.status === "stopped" &&
    (playback.track_id !== null ||
      playback.playlist_id !== null ||
      playback.position_ms !== 0 ||
      playback.loop ||
      playback.audience.length !== 0 ||
      playback.started_at_ms !== null);
  const activeStateIsInvalid =
    playback.status !== "stopped" &&
    (playback.track_id === null ||
      playback.audience.length === 0 ||
      (playback.status === "playing") !== (playback.started_at_ms !== null));
  if (stoppedStateIsInvalid || activeStateIsInvalid) {
    throw new Error("presentation.playback is inconsistent");
  }
  return playback;
}

function parseCamera(value: unknown): SharedCamera {
  const data = exactObject(
    value,
    [
      "schema_version",
      "enabled",
      "epoch",
      "scene_id",
      "center_x_ft",
      "center_y_ft",
      "zoom",
    ],
    "presentation.camera",
  );
  const camera: SharedCamera = {
    schema_version: literal(
      data.schema_version,
      ["vtt.presentation_camera.v1"] as const,
      "presentation.camera.schema_version",
    ),
    enabled: booleanValue(data.enabled, "presentation.camera.enabled"),
    epoch: safeInteger(data.epoch, "presentation.camera.epoch"),
    scene_id: nullableText(data.scene_id, "presentation.camera.scene_id"),
    center_x_ft: nullableFinite(
      data.center_x_ft,
      "presentation.camera.center_x_ft",
    ),
    center_y_ft: nullableFinite(
      data.center_y_ft,
      "presentation.camera.center_y_ft",
    ),
    zoom: nullableFinite(data.zoom, "presentation.camera.zoom"),
  };
  const complete =
    camera.scene_id !== null &&
    camera.center_x_ft !== null &&
    camera.center_y_ft !== null &&
    camera.zoom !== null &&
    camera.zoom >= 1 &&
    camera.zoom <= 4;
  if (camera.enabled !== complete) {
    throw new Error("presentation.camera is inconsistent");
  }
  return camera;
}

export function parsePresentationView(value: unknown): PresentationView {
  const data = exactObject(
    value,
    [
      "schema_version",
      "session_id",
      "table_id",
      "revision",
      "server_epoch_ms",
      "tracks",
      "playlists",
      "playback",
      "camera",
    ],
    "presentation",
  );
  if (!Array.isArray(data.tracks) || !Array.isArray(data.playlists)) {
    throw new Error("presentation library must be arrays");
  }
  const tracks = data.tracks.map((item, index) =>
    parseSoundTrack(item, `presentation.tracks[${index}]`),
  );
  const playlists = data.playlists.map((item, index) =>
    parseSoundPlaylist(item, `presentation.playlists[${index}]`),
  );
  const trackIds = tracks.map((item) => item.track_id);
  const playlistIds = playlists.map((item) => item.playlist_id);
  if (
    trackIds.some(
      (trackId, index) =>
        index > 0 && compareCodePoints(trackIds[index - 1], trackId) >= 0,
    ) ||
    playlistIds.some(
      (playlistId, index) =>
        index > 0 && compareCodePoints(playlistIds[index - 1], playlistId) >= 0,
    )
  ) {
    throw new Error("presentation library must be unique and sorted");
  }
  const playback = parsePlayback(data.playback);
  const knownTracks = new Set(trackIds);
  if (
    playlists.some((item) => item.track_ids.some((trackId) => !knownTracks.has(trackId))) ||
    (playback.track_id !== null && !knownTracks.has(playback.track_id))
  ) {
    throw new Error("presentation has a missing track reference");
  }
  return {
    schema_version: literal(
      data.schema_version,
      ["vtt.presentation_view.v1"] as const,
      "presentation.schema_version",
    ),
    session_id: canonicalText(data.session_id, "presentation.session_id", 128),
    table_id: canonicalText(data.table_id, "presentation.table_id", 128),
    revision: safeInteger(data.revision, "presentation.revision"),
    server_epoch_ms: safeInteger(data.server_epoch_ms, "presentation.server_epoch_ms"),
    tracks,
    playlists,
    playback,
    camera: parseCamera(data.camera),
  };
}

export function parsePresentationSignal(value: unknown): PresentationSignal {
  const data = exactObject(
    value,
    ["schema_version", "sequence", "revision"],
    "presentation_signal",
  );
  const sequence = safeInteger(data.sequence, "presentation_signal.sequence", 1);
  const revision = safeInteger(data.revision, "presentation_signal.revision", 1);
  if (sequence !== revision) {
    throw new Error("presentation signal identity mismatch");
  }
  return {
    schema_version: literal(
      data.schema_version,
      ["vtt.presentation_signal.v1"] as const,
      "presentation_signal.schema_version",
    ),
    sequence,
    revision,
  };
}

export function parsePresentationResponse(value: unknown): PresentationResponse {
  const data = exactObject(
    value,
    ["schema_version", "session_id", "replayed", "receipt"],
    "presentation_response",
  );
  const receipt = exactObject(
    data.receipt,
    ["schema_version", "table_id", "command_id", "revision", "signal"],
    "presentation_response.receipt",
  );
  const signal = parsePresentationSignal(receipt.signal);
  const revision = safeInteger(
    receipt.revision,
    "presentation_response.receipt.revision",
    1,
  );
  if (revision !== signal.revision) {
    throw new Error("presentation response revision mismatch");
  }
  return {
    schema_version: literal(
      data.schema_version,
      ["vtt.presentation_response.v1"] as const,
      "presentation_response.schema_version",
    ),
    session_id: canonicalText(data.session_id, "presentation_response.session_id", 128),
    replayed: booleanValue(data.replayed, "presentation_response.replayed"),
    receipt: {
      schema_version: literal(
        receipt.schema_version,
        ["vtt.presentation_receipt.v1"] as const,
        "presentation_response.receipt.schema_version",
      ),
      table_id: canonicalText(
        receipt.table_id,
        "presentation_response.receipt.table_id",
        128,
      ),
      command_id: canonicalText(
        receipt.command_id,
        "presentation_response.receipt.command_id",
        128,
      ),
      revision,
      signal,
    },
  };
}

export async function getPresentation(
  signal: AbortSignal | undefined,
  bearerToken: string | null,
): Promise<PresentationView> {
  const response = await fetch(`${VTT_API_BASE_URL}/api/v1/presentation`, {
    signal,
    headers: buildVttRequestHeaders({
      accept: "application/json",
      bearerToken,
    }),
  });
  const value = await responseJson(response);
  return parsePresentationView(value);
}

export async function postPresentationCommand(
  sessionId: string,
  command: PresentationCommand,
  bearerToken: string | null,
): Promise<PresentationResponse> {
  const response = await fetch(
    `${VTT_API_BASE_URL}/api/v1/presentation-commands`,
    {
      method: "POST",
      headers: buildVttRequestHeaders({
        accept: "application/json",
        bearerToken,
        contentType: "application/json",
      }),
      body: JSON.stringify({
        schema_version: "vtt.presentation_request.v1",
        session_id: sessionId,
        command,
      }),
    },
  );
  const value = await responseJson(response);
  const parsed = parsePresentationResponse(value);
  if (
    parsed.session_id !== sessionId ||
    parsed.receipt.table_id !== command.table_id ||
    parsed.receipt.command_id !== command.command_id
  ) {
    throw new Error("Presentation response does not match its request.");
  }
  return parsed;
}

export function commandBase(input: {
  tableId: string;
  revision: number;
  commandType: string;
}): PresentationCommand {
  return {
    schema_version: "vtt.presentation_command.v1",
    command_type: input.commandType,
    table_id: canonicalText(input.tableId, "tableId", 128),
    command_id: crypto.randomUUID(),
    expected_revision: safeInteger(input.revision, "revision"),
  };
}

export async function blobToBase64(blob: Blob): Promise<string> {
  const bytes = new Uint8Array(await blob.arrayBuffer());
  let value = "";
  for (let index = 0; index < bytes.length; index += 0x8000) {
    value += String.fromCharCode(...bytes.subarray(index, index + 0x8000));
  }
  return btoa(value);
}

export async function fetchSoundBlob(
  track: SoundTrack,
  bearerToken: string | null,
  signal?: AbortSignal,
): Promise<Blob> {
  const response = await fetch(`${VTT_API_BASE_URL}${track.content_path}`, {
    signal,
    headers: buildVttRequestHeaders({
      accept: track.media_type,
      bearerToken,
    }),
  });
  if (!response.ok) await responseJson(response);
  if (response.headers.get("content-type")?.split(";", 1)[0] !== track.media_type) {
    throw new Error("Sound asset MIME type does not match its record.");
  }
  const bytes = await response.arrayBuffer();
  const digest = Array.from(
    new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)),
    (item) => item.toString(16).padStart(2, "0"),
  ).join("");
  if (digest !== track.sha256) {
    throw new Error("Sound asset digest does not match its record.");
  }
  return new Blob([bytes], { type: track.media_type });
}
