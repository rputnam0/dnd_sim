import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { attemptSharedAudioPlayback, VttPresentationPanel } from "../app/vtt-presentation-panel";
import { commandBase, parsePresentationSignal, parsePresentationView } from "../app/vtt-presentation";
import type { VttPresentationController } from "../app/use-vtt-presentation";
import type { VttTableParticipant, VttTableView } from "../app/vtt-access";

const participant: VttTableParticipant = {
  schema_version: "vtt.participant.v1",
  participant_id: "gm",
  display_name: "Game Master",
  role: "gm",
  owned_actor_ids: [],
};
const table: VttTableView = {
  schema_version: "vtt.table_view.v1",
  access_mode: "open_local",
  table_id: "table-a",
  current_participant: participant,
  participants: [participant],
};

const stopped = { schema_version: "vtt.sound_playback.v1", status: "stopped", track_id: null, playlist_id: null, position_ms: 0, loop: false, audience: [], started_at_ms: null };
const camera = { schema_version: "vtt.presentation_camera.v1", enabled: false, epoch: 0, scene_id: null, center_x_ft: null, center_y_ft: null, zoom: null };
const view = { schema_version: "vtt.presentation_view.v1", session_id: "session-a", table_id: "table-a", revision: 0, server_epoch_ms: 1000, tracks: [], playlists: [], playback: stopped, camera };

test("strictly parses presentation identity, sound state, and sanitized signals", () => {
  assert.deepEqual(parsePresentationView(view), view);
  assert.deepEqual(parsePresentationSignal({ schema_version: "vtt.presentation_signal.v1", sequence: 2, revision: 2 }), { schema_version: "vtt.presentation_signal.v1", sequence: 2, revision: 2 });
  assert.throws(() => parsePresentationView({ ...view, secret: "leak" }), /unexpected field/);
  assert.throws(() => parsePresentationView({ ...view, camera: { ...camera, enabled: true } }), /inconsistent/);
  assert.throws(() => parsePresentationSignal({ schema_version: "vtt.presentation_signal.v1", sequence: 2, revision: 3 }), /identity/);
});

test("presentation command construction never includes local volume or follow preferences", () => {
  const command = { ...commandBase({ tableId: "table-a", revision: 4, commandType: "play" }), track_id: "hum", playlist_id: null, position_ms: 0, loop: true, audience: ["all"] };
  assert.equal(command.command_type, "play");
  assert.equal("volume" in command, false);
  assert.equal("follow" in command, false);
});

test("renders native player recovery and GM sound camera controls", () => {
  const controller: VttPresentationController = { view: parsePresentationView(view), camera: null, followCamera: false, setFollowCamera: () => undefined, status: "live", error: null, canManage: true, mutate: async () => undefined, retry: () => undefined };
  const html = renderToStaticMarkup(createElement(VttPresentationPanel, { table, bearerToken: null, activeSceneId: "echo-vault", controller }));
  assert.match(html, /Local volume/);
  assert.match(html, /Follow GM view/);
  assert.match(html, /Upload track/);
  assert.match(html, /Play for table/);
  assert.match(html, /Save playlist/);
  assert.match(html, /Share view/);
  assert.match(html, /Stop sharing/);
  assert.match(html, /type="file"/);
  assert.match(html, /type="range"/);
});

test("autoplay rejection stays paused until an explicit retry succeeds", async () => {
  let attempts = 0;
  let pauses = 0;
  const audio = {
    play: async () => { attempts += 1; if (attempts === 1) throw new Error("blocked"); },
    pause: () => { pauses += 1; },
  };
  assert.equal(await attemptSharedAudioPlayback(audio), false);
  assert.equal(pauses, 1);
  assert.equal(await attemptSharedAudioPlayback(audio), true);
  assert.equal(attempts, 2);
});
