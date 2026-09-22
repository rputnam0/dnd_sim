import assert from "node:assert/strict";
import test from "node:test";

import {
  decodeWorkspacePreferences,
  encodeWorkspacePreferences,
  panelsForRole,
  panelsForWorkspace,
  resolveWorkspacePreferences,
  type VttWorkspacePanelAccess,
} from "../app/vtt-workspace-state";

const panels: VttWorkspacePanelAccess[] = [
  { id: "combat", modes: ["play"] },
  { id: "chat", modes: ["play"] },
  { id: "journal", modes: ["play", "prepare"] },
  { id: "scenes", modes: ["prepare"], roles: ["gm"] },
  { id: "tokens", modes: ["prepare"], roles: ["gm"] },
  { id: "gm-events", modes: ["play"], roles: ["gm"] },
];

test("workspace preferences round-trip only a validated mode and panel ID", () => {
  const serialized = encodeWorkspacePreferences(
    { mode: "prepare", panelId: "tokens" },
    { role: "gm", panels },
  );

  assert.equal(serialized, '{"mode":"prepare","panel_id":"tokens"}');
  assert.deepEqual(decodeWorkspacePreferences(serialized), {
    mode: "prepare",
    panelId: "tokens",
  });
  assert.throws(
    () =>
      encodeWorkspacePreferences(
        { mode: "prepare", panelId: "missing" },
        { role: "gm", panels },
      ),
    /available panel/i,
  );
});

test("preference decoding rejects credentials, extra data, and malformed IDs", () => {
  assert.equal(
    decodeWorkspacePreferences(
      '{"mode":"play","panel_id":"combat","bearer_token":"secret"}',
    ),
    null,
  );
  assert.equal(
    decodeWorkspacePreferences('{"mode":"play","panel_id":"../../token"}'),
    null,
  );
  assert.equal(decodeWorkspacePreferences("not-json"), null);
});

test("workspace resolution cannot elevate players or spectators into Prepare", () => {
  assert.deepEqual(
    resolveWorkspacePreferences({
      candidate: { mode: "prepare", panelId: "scenes" },
      role: "player",
      panels,
    }),
    { mode: "play", panelId: "combat" },
  );
  assert.deepEqual(
    panelsForWorkspace(panels, "player", "play").map((panel) => panel.id),
    ["combat", "chat", "journal"],
  );
  assert.deepEqual(
    panelsForWorkspace(panels, "spectator", "prepare").map(
      (panel) => panel.id,
    ),
    [],
  );
  assert.deepEqual(
    panelsForWorkspace(panels, "gm", "prepare").map((panel) => panel.id),
    ["journal", "scenes", "tokens"],
  );
});

test("invalid or stale stored panel IDs fall back inside the permitted workspace", () => {
  assert.deepEqual(
    resolveWorkspacePreferences({
      candidate: { mode: "play", panelId: "retired-panel" },
      role: "gm",
      panels,
    }),
    { mode: "play", panelId: "combat" },
  );
  assert.deepEqual(
    resolveWorkspacePreferences({
      candidate: null,
      role: "gm",
      panels: [{ id: "scenes", modes: ["prepare"], roles: ["gm"] }],
    }),
    { mode: "prepare", panelId: "scenes" },
  );
});

test("role authorization spans GM workspaces but never exposes Prepare-only panels", () => {
  assert.deepEqual(
    panelsForRole(panels, "gm").map((panel) => panel.id),
    ["combat", "chat", "journal", "scenes", "tokens", "gm-events"],
  );
  assert.deepEqual(
    panelsForRole(panels, "player").map((panel) => panel.id),
    ["combat", "chat", "journal"],
  );
});
