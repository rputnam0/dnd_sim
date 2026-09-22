import assert from "node:assert/strict";
import test from "node:test";

import {
  buildDoorStateRequest,
  buildVisibilityPutRequest,
  expandVisibilityMask,
  getVisibilityProjection,
  parseVisibilityCatalog,
  parseVisibilityProjection,
  parseVisibilitySseBlock,
  visibilityProjectionMatchesSources,
  type SceneEnvironment,
} from "../app/vtt-visibility";
import { paintVisibilityMask } from "../app/vtt-visibility-mask";

const ENVIRONMENT: SceneEnvironment = {
  schema_version: "vtt.scene_environment.v1",
  record_type: "environment",
  record_id: "scene-environment",
  scene_id: "echo-vault",
  darkness: "darkness",
  shared_vision: "owned_only",
};

const TOKEN = {
  schema_version: "vtt.token_record.v1" as const,
  token_id: "vela-token",
  scene_id: "echo-vault",
  actor_id: "vela_quill",
  name: "Vela Quill",
  pose: {
    schema_version: "vtt.token_pose.v1" as const,
    position_ft: { x_ft: 12.5, y_ft: 12.5, z_ft: 0 },
    width_ft: 5,
    height_ft: 5,
    rotation_degrees: 0,
    layer: 0,
  },
  visibility: "owners" as const,
  locked: false,
  nameplate: "always" as const,
  show_hp_bar: true,
  aura_radius_ft: 0,
  aura_color: "#4DD7B3",
  condition_labels: [],
};

const PROJECTION = {
  schema_version: "vtt.visibility_projection.v1" as const,
  table_id: "table-a",
  scene_id: "echo-vault",
  scene_revision: 3,
  token_revision: 4,
  visibility_revision: 5,
  encounter_revision: 6,
  mask_width: 4,
  mask_height: 2,
  visible_runs: [
    { schema_version: "vtt.visibility_mask_run.v1" as const, start: 0, length: 2 },
    { schema_version: "vtt.visibility_mask_run.v1" as const, start: 4, length: 3 },
  ],
  tokens: [TOKEN],
};

test("strictly separates GM visibility records from the player projection", () => {
  const catalog = parseVisibilityCatalog({
    schema_version: "vtt.visibility_catalog_view.v1",
    table_id: "table-a",
    scene_id: "echo-vault",
    revision: 1,
    records: [ENVIRONMENT],
  });
  assert.equal(catalog.records[0].record_type, "environment");
  assert.throws(() => parseVisibilityCatalog({ ...catalog, hidden_actor_ids: ["secret"] }));

  const projection = parseVisibilityProjection(PROJECTION);
  assert.deepEqual([...expandVisibilityMask(projection)], [1, 1, 0, 0, 1, 1, 1, 0]);
  assert.equal(projection.tokens[0].token_id, "vela-token");
  assert.throws(() => parseVisibilityProjection({
    ...PROJECTION,
    visible_runs: [
      { schema_version: "vtt.visibility_mask_run.v1", start: 0, length: 4 },
      { schema_version: "vtt.visibility_mask_run.v1", start: 4, length: 1 },
    ],
  }));
  assert.throws(() => parseVisibilityProjection({ ...PROJECTION, barriers: [] }));
});

test("builds exact revision-bound visibility and door commands", () => {
  assert.deepEqual(buildVisibilityPutRequest({
    sessionId: "session-a",
    tableId: "table-a",
    expectedRevision: 2,
    commandId: "set-environment",
    record: ENVIRONMENT,
  }), {
    schema_version: "vtt.visibility_request.v1",
    session_id: "session-a",
    command: {
      schema_version: "vtt.visibility_command.v1",
      command_type: "put",
      table_id: "table-a",
      command_id: "set-environment",
      expected_revision: 2,
      record: ENVIRONMENT,
    },
  });
  assert.equal(buildDoorStateRequest({
    sessionId: "session-a",
    tableId: "table-a",
    expectedRevision: 3,
    commandId: "open-door",
    sceneId: "echo-vault",
    barrierId: "vault-door",
    portalState: "open",
  }).command.command_type, "set_door_state");
});

test("accepts only identity-free visibility SSE signals", () => {
  const event = parseVisibilitySseBlock(
    'id: 5\nevent: vtt.visibility_changed\ndata: {"schema_version":"vtt.visibility_change_signal.v1","sequence":5,"revision":5,"scene_id":"echo-vault"}\n\n',
  );
  assert.equal(event?.revision, 5);
  assert.throws(() => parseVisibilitySseBlock(
    'id: 5\nevent: vtt.visibility_changed\ndata: {"schema_version":"vtt.visibility_change_signal.v1","sequence":5,"revision":5,"scene_id":"echo-vault","barrier_id":"secret"}\n\n',
  ));
  assert.throws(() => parseVisibilitySseBlock(
    'id: 4\nevent: vtt.visibility_changed\ndata: {"schema_version":"vtt.visibility_change_signal.v1","sequence":5,"revision":5,"scene_id":"echo-vault"}\n\n',
  ));
});

test("loads the player projection with bearer auth and no participant selector", async () => {
  const originalFetch = globalThis.fetch;
  let observed: Request | null = null;
  globalThis.fetch = async (input, init) => {
    observed = input instanceof Request ? input : new Request(input, init);
    return Response.json(PROJECTION);
  };
  try {
    const projection = await getVisibilityProjection(undefined, "private-token-1234");
    assert.equal(projection.visibility_revision, 5);
    assert.match(observed!.url, /\/api\/v1\/visibility$/);
    assert.equal(observed!.headers.get("authorization"), "Bearer private-token-1234");
    assert.doesNotMatch(observed!.url, /participant|private-token/);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("paints hidden first and clears only bounded server-visible runs", () => {
  const calls: Array<[string, number, number, number, number]> = [];
  const context = {
    fillStyle: "",
    clearRect: (x: number, y: number, width: number, height: number) => {
      calls.push(["clear", x, y, width, height]);
    },
    fillRect: (x: number, y: number, width: number, height: number) => {
      calls.push(["fill", x, y, width, height]);
    },
  };
  paintVisibilityMask(context, parseVisibilityProjection(PROJECTION));

  assert.deepEqual(calls, [
    ["clear", 0, 0, 4, 2],
    ["fill", 0, 0, 4, 2],
    ["clear", 0, 0, 2, 1],
    ["clear", 0, 1, 3, 1],
  ]);
  assert.equal(context.fillStyle, "#020707");
});

test("requires all four authoritative revisions before presenting a mask", () => {
  const projection = parseVisibilityProjection(PROJECTION);
  const exact = {
    sceneId: "echo-vault",
    sceneRevision: 3,
    tokenRevision: 4,
    visibilityRevision: 5,
    encounterRevision: 6,
  };

  assert.equal(visibilityProjectionMatchesSources(projection, exact), true);
  for (const mismatch of [
    { ...exact, sceneId: "other-scene" },
    { ...exact, sceneRevision: 30 },
    { ...exact, tokenRevision: 40 },
    { ...exact, visibilityRevision: 50 },
    { ...exact, encounterRevision: 60 },
  ]) {
    assert.equal(visibilityProjectionMatchesSources(projection, mismatch), false);
  }
  assert.equal(
    visibilityProjectionMatchesSources(projection, {
      ...exact,
      visibilityRevision: null,
    }),
    false,
  );
  assert.equal(visibilityProjectionMatchesSources(null, exact), false);
});
