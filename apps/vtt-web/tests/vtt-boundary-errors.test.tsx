import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import TestRenderer, { act } from "react-test-renderer";

import { VttApiError } from "../app/vtt-client";
import {
  buildJournalDeleteDocumentRequest,
  getJournalView,
  postJournalRequest,
  streamJournalEvents,
} from "../app/vtt-journal";
import {
  commandBase,
  fetchSoundBlob,
  getPresentation,
  parsePresentationView,
  postPresentationCommand,
  type SoundTrack,
} from "../app/vtt-presentation";
import { useVttPresentation } from "../app/use-vtt-presentation";
import { parseVttRollCard } from "../app/vtt-roll-cards";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const token = "protected-table-boundary-token";
const errorBody = {
  schema_version: "vtt.error.v1",
  code: "authentication_required",
  message: "The table credential is no longer valid.",
  details: {},
};
const track: SoundTrack = {
  schema_version: "vtt.sound_track.v1",
  track_id: "vault-hum",
  name: "Vault hum",
  media_type: "audio/wav",
  content_path: "/api/v1/sound-assets/vault-hum/content.wav",
  sha256: "0".repeat(64),
  byte_size: 1,
};

function isAuthenticationError(error: unknown): boolean {
  assert.ok(error instanceof VttApiError);
  assert.equal(error.status, 401);
  assert.equal(error.code, errorBody.code);
  assert.equal(error.message, errorBody.message);
  assert.deepEqual(error.details, {});
  return true;
}

for (const operation of ["journal read", "journal write", "journal stream", "presentation read", "presentation write", "sound asset"] as const) {
  test(`${operation} preserves a typed authentication failure and transport headers`, async (context) => {
    let headers: Headers | undefined;
    context.mock.method(globalThis, "fetch", async (_url: unknown, init?: RequestInit) => {
      headers = new Headers(init?.headers);
      return Response.json(errorBody, { status: 401 });
    });
    const signal = new AbortController().signal;
    const operations = {
      "journal read": () => getJournalView(signal, token),
      "journal write": () => postJournalRequest(buildJournalDeleteDocumentRequest({
        sessionId: "session-a", tableId: "table-a", expectedRevision: 0,
        documentId: "document-a", commandId: "delete-document-a",
      }), token),
      "journal stream": () => streamJournalEvents({ after: 0, bearerToken: token, signal, onEvent: () => undefined }),
      "presentation read": () => getPresentation(signal, token),
      "presentation write": () => postPresentationCommand("session-a", commandBase({ tableId: "table-a", revision: 0, commandType: "stop" }), token),
      "sound asset": () => fetchSoundBlob(track, token, signal),
    };
    await assert.rejects(operations[operation], isAuthenticationError);
    assert.equal(headers?.get("authorization"), `Bearer ${token}`);
    assert.equal(headers?.get("accept"), operation === "journal stream" ? "text/event-stream" : operation === "sound asset" ? "audio/wav" : "application/json");
    if (operation.endsWith("write")) assert.equal(headers?.get("content-type"), "application/json");
  });
}

test("journal conflict retains the revision details used for recovery", async (context) => {
  context.mock.method(globalThis, "fetch", async () => Response.json({
    schema_version: "vtt.error.v1", code: "revision_conflict",
    message: "Refresh the journal before retrying.", details: { current_revision: 3 },
  }, { status: 409 }));
  await assert.rejects(() => postJournalRequest(buildJournalDeleteDocumentRequest({
    sessionId: "session-a", tableId: "table-a", expectedRevision: 0,
    documentId: "document-a", commandId: "delete-document-a",
  }), token), (error: unknown) => {
    assert.ok(error instanceof VttApiError);
    assert.equal(error.status, 409);
    assert.equal(error.code, "revision_conflict");
    assert.deepEqual(error.details, { current_revision: 3 });
    return true;
  });
});

test("private sound lookup with an empty error body still preserves HTTP status", async (context) => {
  context.mock.method(globalThis, "fetch", async () => new Response(null, { status: 404 }));
  await assert.rejects(() => fetchSoundBlob(track, token), (error: unknown) => {
    assert.ok(error instanceof VttApiError);
    assert.equal(error.status, 404);
    assert.equal(error.code, "invalid_response");
    assert.doesNotMatch(error.message, /fromResponse/);
    return true;
  });
});

test("presentation stream authentication failure clears the private view and displays its message", async (context) => {
  const view = parsePresentationView({
    schema_version: "vtt.presentation_view.v1", session_id: "session-a", table_id: "table-a",
    revision: 0, server_epoch_ms: 1000, tracks: [], playlists: [],
    playback: { schema_version: "vtt.sound_playback.v1", status: "stopped", track_id: null, playlist_id: null, position_ms: 0, loop: false, audience: [], started_at_ms: null },
    camera: { schema_version: "vtt.presentation_camera.v1", enabled: false, epoch: 0, scene_id: null, center_x_ft: null, center_y_ft: null, zoom: null },
  });
  context.mock.method(globalThis, "fetch", async (url: unknown) => String(url).includes("presentation-events")
    ? Response.json(errorBody, { status: 401 })
    : Response.json(view));
  const previousWindow = Object.getOwnPropertyDescriptor(globalThis, "window");
  Object.defineProperty(globalThis, "window", { configurable: true, value: { setTimeout: () => 0 } });
  let current: ReturnType<typeof useVttPresentation> | undefined;
  function Harness() {
    current = useVttPresentation({
      sessionId: "session-a", tableId: "table-a", bearerToken: token, activeSceneId: null,
      participant: { schema_version: "vtt.participant.v1", participant_id: "gm", display_name: "GM", role: "gm", owned_actor_ids: [] },
    });
    return createElement("output", null, current.error);
  }
  let renderer: TestRenderer.ReactTestRenderer | undefined;
  try {
    await act(async () => { renderer = TestRenderer.create(createElement(Harness)); });
    assert.equal(current?.status, "error");
    assert.equal(current?.error, errorBody.message);
    assert.equal(current?.view, null);
  } finally {
    await act(async () => { renderer?.unmount(); });
    if (previousWindow) Object.defineProperty(globalThis, "window", previousWindow);
    else Reflect.deleteProperty(globalThis, "window");
  }
});

test("malformed roll faces identify their field without interpolating the entire face array", () => {
  const face = { schema_version: "vtt.roll_card_face.v1", generation_index: 1, sides: 8, value: 9, status: "kept", replacement_generation_index: null };
  assert.throws(() => parseVttRollCard({
    schema_version: "vtt.roll_card.v1", card_id: "roll:boundary", roll_sequence: 1,
    source_actor_id: "hero", target_actor_id: null, action_id: null, purpose: "damage",
    fact: {
      schema_version: "vtt.roll_card_damage_fact.v1", kind: "damage", expression: "1d8",
      faces: [face], damage_type: "force", flat_modifier: 0, rolled_total: 9,
      raw_damage: 9, applied_damage: 9, critical: false, adjustments: [],
    },
  }), { message: "roll_card.fact.faces[0].value exceeds its die" });
});
