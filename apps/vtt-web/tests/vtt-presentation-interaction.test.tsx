import assert from "node:assert/strict";
import test from "node:test";
import { createElement, useState } from "react";
import TestRenderer, { act } from "react-test-renderer";

import { VttPresentationPanel } from "../app/vtt-presentation-panel";
import { parsePresentationView, type PresentationView } from "../app/vtt-presentation";
import type { VttTableParticipant, VttTableView } from "../app/vtt-access";

const reactTestEnvironment: typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean } = globalThis;
reactTestEnvironment.IS_REACT_ACT_ENVIRONMENT = true;

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

const track = {
  schema_version: "vtt.sound_track.v1" as const,
  track_id: "vault-hum",
  name: "Vault hum",
  media_type: "audio/wav" as const,
  content_path: "/api/v1/sound-assets/vault-hum/content.wav",
  sha256: "6e340b9cffb37a989ca544e6bb780a2c78901d3fb33738768511a30617afa01d",
  byte_size: 1,
};

test("mounted sound desk drives playlist playback camera and local controls", async () => {
  const mutations: Array<{ type: string; fields: Record<string, unknown> }> = [];
  const follow: boolean[] = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response(new Uint8Array([0]), { headers: { "content-type": "audio/wav" } });

  function Harness() {
    const [view, setView] = useState<PresentationView>({
      schema_version: "vtt.presentation_view.v1",
      session_id: "session-a",
      table_id: "table-a",
      revision: 1,
      server_epoch_ms: 1_000,
      tracks: [track],
      playlists: [],
      playback: { schema_version: "vtt.sound_playback.v1", status: "stopped", track_id: null, playlist_id: null, position_ms: 0, loop: false, audience: [], started_at_ms: null },
      camera: { schema_version: "vtt.presentation_camera.v1", enabled: false, epoch: 0, scene_id: null, center_x_ft: null, center_y_ft: null, zoom: null },
    });
    const mutate = async (type: string, fields: Record<string, unknown>) => {
      mutations.push({ type, fields });
      setView((current) => {
        if (type === "put_playlist") return parsePresentationView({ ...current, revision: current.revision + 1, playlists: [fields.playlist] });
        if (type === "play") return { ...current, revision: current.revision + 1, playback: { schema_version: "vtt.sound_playback.v1", status: "playing", track_id: track.track_id, playlist_id: null, position_ms: 0, loop: true, audience: ["all"], started_at_ms: 1_000 } };
        if (type === "pause") return { ...current, revision: current.revision + 1, playback: { ...current.playback, status: "paused", started_at_ms: null } };
        if (type === "stop") return { ...current, revision: current.revision + 1, playback: { schema_version: "vtt.sound_playback.v1", status: "stopped", track_id: null, playlist_id: null, position_ms: 0, loop: false, audience: [], started_at_ms: null } };
        if (type === "share_camera") return { ...current, revision: current.revision + 1, camera: { schema_version: "vtt.presentation_camera.v1", enabled: true, epoch: 1, scene_id: "echo-vault", center_x_ft: Number(fields.center_x_ft), center_y_ft: Number(fields.center_y_ft), zoom: Number(fields.zoom) } };
        if (type === "disable_camera") return { ...current, revision: current.revision + 1, camera: { schema_version: "vtt.presentation_camera.v1", enabled: false, epoch: 2, scene_id: null, center_x_ft: null, center_y_ft: null, zoom: null } };
        return { ...current, revision: current.revision + 1 };
      });
    };
    return createElement(VttPresentationPanel, {
      table,
      bearerToken: null,
      activeSceneId: "echo-vault",
      controller: { view, camera: view.camera.enabled ? view.camera : null, followCamera: false, setFollowCamera: (value: boolean) => follow.push(value), status: "live", error: null, canManage: true, mutate, retry: () => undefined },
    });
  }

  let renderer: TestRenderer.ReactTestRenderer;
  await act(async () => { renderer = TestRenderer.create(createElement(Harness)); });
  const root = renderer!.root;
  const button = (name: string) => root.findAllByType("button").find((item) => item.children.join("") === name)!;

  await act(async () => { button("Save playlist").props.onClick(); });
  await act(async () => { button("Play for table").props.onClick(); });
  await act(async () => { button("Pause").props.onClick(); });
  await act(async () => { button("Stop").props.onClick(); });
  await act(async () => { button("Share view").props.onClick(); });
  await act(async () => { button("Stop sharing").props.onClick(); });

  const range = root.findByProps({ type: "range" });
  await act(async () => { range.props.onChange({ currentTarget: { value: "32" } }); });
  const checkboxes = root.findAllByProps({ type: "checkbox" });
  await act(async () => { checkboxes[1].props.onChange({ currentTarget: { checked: true } }); });
  assert.deepEqual(follow, [true]);
  assert.deepEqual(mutations.slice(0, 6).map((item) => item.type), ["put_playlist", "play", "pause", "stop", "share_camera", "disable_camera"]);
  assert.equal(mutations.some((item) => "volume" in item.fields), false);

  await act(async () => { renderer!.unmount(); });
  globalThis.fetch = originalFetch;
});
