import assert from "node:assert/strict";
import test from "node:test";

import {
  buildDeclarationCommand,
  buildStartCommand,
  feetToCell,
  parseCommandResponse,
  parseSessionView,
} from "../app/vtt-client";

const sessionView = {
  schema_version: "vtt.session_view.v1",
  session_id: "echo-vault-session",
  revision: 1,
  versions: {
    schema_version: "vtt.version_info.v1",
    engine: "dnd-sim@0.1.0",
    rules: "5e_2014_combat_foundation@1.0.0",
    content: "solo-table.echo-vault@1.0.0",
  },
  scene: {
    schema_version: "vtt.scene.v1",
    scene_id: "echo-vault",
    name: "Echo Vault",
    grid_type: "square",
    cell_size_ft: 5,
    columns: 8,
    rows: 6,
    origin_ft: { x_ft: 0, y_ft: 0, z_ft: 0 },
  },
  projection: {
    phase: "awaiting_declaration",
    outcome: null,
    winner: null,
    current_index: 0,
    active_actor_id: "vela_quill",
    round_number: 1,
    max_rounds: 4,
    initiative_order: ["vela_quill", "hushglass_sentry"],
    actors: {
      vela_quill: {
        actor_id: "vela_quill",
        team: "party",
        name: "Vela Quill",
        hp: 24,
        max_hp: 24,
        temp_hp: 0,
        ac: 15,
        position: [12.5, 12.5, 0],
        movement_remaining: 30,
        conditions: [],
        dead: false,
        stable: false,
        bonus_available: true,
        reaction_available: true,
        actions: [
          {
            name: "Lattice Lance",
            action_type: "attack",
            action_cost: "action",
            target_mode: "single_enemy",
            reach_ft: 5,
            range_normal_ft: null,
            range_long_ft: null,
          },
        ],
      },
      hushglass_sentry: {
        actor_id: "hushglass_sentry",
        team: "enemy",
        name: "Hushglass Sentry",
        hp: 7,
        max_hp: 7,
        temp_hp: 0,
        ac: 12,
        position: [17.5, 12.5, 0],
        movement_remaining: 30,
        conditions: [],
        dead: false,
        stable: false,
        bonus_available: true,
        reaction_available: true,
        actions: [
          {
            name: "Quietus Needle",
            action_type: "attack",
            action_cost: "action",
            target_mode: "single_enemy",
            reach_ft: 5,
            range_normal_ft: null,
            range_long_ft: null,
          },
        ],
      },
    },
    prompt: {
      actor_id: "vela_quill",
      round_number: 1,
      turn_token: "round:1:actor:vela_quill",
    },
    result: null,
  },
} as const;

test("builds the complete canonical D&D declaration command", () => {
  const command = buildDeclarationCommand({
    commandId: "preview-command",
    sessionId: "echo-vault-session",
    expectedRevision: 1,
    actorId: "vela_quill",
    actionName: "Lattice Lance",
    targetIds: ["hushglass_sentry"],
    mode: "preview",
  });

  assert.deepEqual(command, {
    schema_version: "vtt.command.v1",
    command_id: "preview-command",
    session_id: "echo-vault-session",
    actor_id: "vela_quill",
    expected_revision: 1,
    mode: "preview",
    kind: "dnd.declare_turn.v1",
    payload: {
      movement_path: [],
      action: {
        action_name: "Lattice Lance",
        targets: [{ actor_id: "hushglass_sentry" }],
        resource_spend: { amounts: {} },
        spell_slot_level: null,
        rationale: {},
      },
      bonus_action: null,
      reaction_policy: { mode: "auto", rationale: {} },
      ready: null,
      rationale: {},
    },
    intent_metadata: {
      surface: "echo-vault-web",
      selected_action: "Lattice Lance",
      selected_targets: ["hushglass_sentry"],
    },
  });
});

test("builds an actor-independent start command with UUID defaults", () => {
  const command = buildStartCommand({
    sessionId: "echo-vault-session",
    expectedRevision: 0,
  });

  assert.match(command.command_id, /^[0-9a-f]{8}-[0-9a-f-]{27}$/i);
  assert.deepEqual(
    { ...command, command_id: "<uuid>" },
    {
      schema_version: "vtt.command.v1",
      command_id: "<uuid>",
      session_id: "echo-vault-session",
      actor_id: null,
      expected_revision: 0,
      mode: "admin",
      kind: "dnd.start_encounter.v1",
      payload: {},
      intent_metadata: { surface: "echo-vault-web" },
    },
  );
});

test("strictly parses the public session view and rejects snapshot leakage", () => {
  const parsed = parseSessionView(sessionView);

  assert.equal(parsed.projection.actors.vela_quill.name, "Vela Quill");
  assert.deepEqual(feetToCell(parsed.scene!, [17.5, 12.5, 0]), {
    column: 3,
    row: 2,
  });

  assert.throws(
    () => parseSessionView({ ...sessionView, snapshot: { actors: {} } }),
    /unexpected field.*snapshot/i,
  );
  assert.throws(
    () =>
      parseSessionView({
        ...sessionView,
        projection: { ...sessionView.projection, phase: "running" },
      }),
    /projection\.phase/i,
  );
});

test("strictly parses preview receipts without advancing the revision", () => {
  const parsed = parseCommandResponse({
    schema_version: "vtt.preview_response.v1",
    response_type: "preview",
    command_id: "preview-command",
    session_id: "echo-vault-session",
    revision: 1,
    versions: sessionView.versions,
    projection: sessionView.projection,
    events: [
      {
        schema_version: "vtt.event_draft.v1",
        kind: "dnd.turn.resolved",
        audience: ["all"],
        payload: { actor_id: "vela_quill", status: "resolved" },
      },
    ],
  });

  assert.equal(parsed.response_type, "preview");
  assert.equal(parsed.revision, 1);
  assert.equal(parsed.events[0].kind, "dnd.turn.resolved");
  assert.throws(
    () =>
      parseCommandResponse({
        ...parsed,
        canonical_state: { actors: {} },
      }),
    /unexpected field.*canonical_state/i,
  );
});
