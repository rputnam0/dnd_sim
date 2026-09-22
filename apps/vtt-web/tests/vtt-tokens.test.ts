import assert from "node:assert/strict";
import test from "node:test";

import {
  buildTokenCreateRequest,
  buildTokenUpdateRequest,
  getTokenView,
  parseTokenView,
  type TokenRecord,
} from "../app/vtt-tokens";

const TOKEN: TokenRecord = {
  schema_version: "vtt.token_record.v1",
  token_id: "vela-token",
  scene_id: "echo-vault",
  actor_id: "vela_quill",
  name: "Vela Quill",
  pose: {
    schema_version: "vtt.token_pose.v1",
    position_ft: { x_ft: 12.5, y_ft: 12.5, z_ft: 0 },
    width_ft: 5,
    height_ft: 5,
    rotation_degrees: 0,
    layer: 0,
  },
  visibility: "owners",
  locked: false,
  nameplate: "always",
  show_hp_bar: true,
  aura_radius_ft: 0,
  aura_color: "#4DD7B3",
  condition_labels: [],
};

test("strictly parses an ordered scene token projection", () => {
  const parsed = parseTokenView({
    schema_version: "vtt.token_view.v1",
    table_id: "table-a",
    scene_id: "echo-vault",
    revision: 2,
    tokens: [
      { ...TOKEN, token_id: "alpha-token", actor_id: null, visibility: "public" },
      TOKEN,
    ],
  });

  assert.equal(parsed.tokens[1].actor_id, "vela_quill");
  assert.throws(() =>
    parseTokenView({ ...parsed, tokens: [...parsed.tokens].reverse() }),
  );
  assert.throws(() =>
    parseTokenView({ ...parsed, tokens: [{ ...TOKEN, visibility: "owners", actor_id: null }] }),
  );
  assert.throws(() => parseTokenView({ ...parsed, hidden_token_ids: ["secret"] }));
});

test("builds exact revision-bound create and update requests", () => {
  assert.deepEqual(
    buildTokenCreateRequest({
      sessionId: "session-a",
      tableId: "table-a",
      commandId: "create-vela",
      expectedRevision: 2,
      token: TOKEN,
    }),
    {
      schema_version: "vtt.token_request.v1",
      session_id: "session-a",
      command: {
        schema_version: "vtt.token_command.v1",
        command_type: "create",
        table_id: "table-a",
        command_id: "create-vela",
        expected_revision: 2,
        token: TOKEN,
      },
    },
  );
  const rotated = { ...TOKEN, pose: { ...TOKEN.pose, rotation_degrees: 90 } };
  const update = buildTokenUpdateRequest({
    sessionId: "session-a",
    tableId: "table-a",
    commandId: "rotate-vela",
    expectedRevision: 3,
    token: rotated,
  });
  assert.equal(update.command.command_type, "update");
  assert.equal(update.command.token.pose.rotation_degrees, 90);
});

test("strictly preserves bounded sorted axial token footprints", () => {
  const hex = parseTokenView({
    schema_version: "vtt.token_view.v1",
    table_id: "table-a",
    scene_id: "hex-room",
    revision: 1,
    tokens: [{
      ...TOKEN,
      scene_id: "hex-room",
      pose: {
        ...TOKEN.pose,
        occupied_hex_cells: [{ q: 1, r: 2 }, { q: 1, r: 3 }],
      },
    }],
  });
  assert.deepEqual(hex.tokens[0].pose.occupied_hex_cells, [
    { q: 1, r: 2 },
    { q: 1, r: 3 },
  ]);
  assert.throws(() => parseTokenView({
    ...hex,
    tokens: [{
      ...hex.tokens[0],
      pose: {
        ...hex.tokens[0].pose,
        occupied_hex_cells: [{ q: 1, r: 3 }, { q: 1, r: 2 }],
      },
    }],
  }));
});

test("loads token projections with bearer auth and encoded scene identity", async () => {
  const originalFetch = globalThis.fetch;
  let observed: Request | null = null;
  globalThis.fetch = async (input, init) => {
    observed = input instanceof Request ? input : new Request(input, init);
    return Response.json({
      schema_version: "vtt.token_view.v1",
      table_id: "table-a",
      scene_id: "Echo Vault β",
      revision: 0,
      tokens: [],
    });
  };
  try {
    const view = await getTokenView("Echo Vault β", undefined, "private-token-1234");
    assert.equal(view.scene_id, "Echo Vault β");
    assert.match(observed!.url, /scene_id=Echo(?:\+|%20)Vault(?:\+|%20)%CE%B2/);
    assert.equal(observed!.headers.get("authorization"), "Bearer private-token-1234");
    assert.doesNotMatch(observed!.url, /private-token/);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
