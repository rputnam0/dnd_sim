import assert from "node:assert/strict";
import test from "node:test";

import {
  buildDeclarationCommand,
  buildStartCommand,
  cellToFeet,
  feetToCell,
  parseCommandResponse,
  parseSessionView,
  parseVttEvent,
  parseVttSseBlock,
  planGridMovement,
  vttEventsUrl,
  streamVttEvents,
} from "../app/vtt-client";

const sessionView = {
  schema_version: "vtt.session_view.v1",
  session_id: "echo-vault-session",
  revision: 1,
  versions: {
    schema_version: "vtt.version_info.v1",
    engine: "dnd-sim@0.1.0",
    rules: "5e_2014_combat_foundation@1.0.0",
    content: "solo-table.echo-vault@1.1.0",
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
        position: [22.5, 12.5, 0],
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
    choices: {
      schema_version: "dnd.turn-choices.v1",
      actor_id: "vela_quill",
      movement: {
        origin: [12.5, 12.5, 0],
        remaining_ft: 30,
      },
      actions: [
        {
          action_name: "Lattice Lance",
          action_cost: "action",
          target_mode: "single_enemy",
          requires_explicit_targets: true,
          selectable_target_ids: ["hushglass_sentry"],
          legal_target_ids: [],
          reason: "no_legal_targets",
        },
      ],
      reason: null,
    },
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
    movementPath: [
      [12.5, 12.5, 0],
      [17.5, 12.5, 0],
    ],
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
      movement_path: [
        [12.5, 12.5, 0],
        [17.5, 12.5, 0],
      ],
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
      movement_waypoints: 2,
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
  assert.deepEqual(parsed.projection.choices?.actions[0], {
    action_name: "Lattice Lance",
    action_cost: "action",
    target_mode: "single_enemy",
    requires_explicit_targets: true,
    selectable_target_ids: ["hushglass_sentry"],
    legal_target_ids: [],
    reason: "no_legal_targets",
  });
  assert.deepEqual(feetToCell(parsed.scene!, [22.5, 12.5, 0]), {
    column: 4,
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

test("rejects malformed or internally inconsistent turn-choice projections", () => {
  const choices = sessionView.projection.choices;
  const action = choices.actions[0];
  const parseWithChoices = (nextChoices: unknown) =>
    parseSessionView({
      ...sessionView,
      projection: { ...sessionView.projection, choices: nextChoices },
    });

  assert.throws(
    () => parseWithChoices({ ...choices, leaked_rule_state: true }),
    /choices.*unexpected field.*leaked_rule_state/i,
  );
  assert.throws(
    () =>
      parseWithChoices({
        ...choices,
        actions: [action, action],
      }),
    /duplicate action names/i,
  );
  assert.throws(
    () =>
      parseWithChoices({
        ...choices,
        actions: [
          {
            ...action,
            selectable_target_ids: ["vela_quill", "hushglass_sentry"],
          },
        ],
      }),
    /selectable_target_ids.*sorted/i,
  );
  assert.throws(
    () =>
      parseWithChoices({
        ...choices,
        actions: [
          {
            ...action,
            selectable_target_ids: ["hushglass_sentry", "hushglass_sentry"],
          },
        ],
      }),
    /selectable_target_ids.*unique/i,
  );
  assert.throws(
    () =>
      parseWithChoices({
        ...choices,
        actions: [
          {
            ...action,
            selectable_target_ids: ["hushglass_sentry", "vela_quill"],
            legal_target_ids: ["vela_quill", "hushglass_sentry"],
            reason: null,
          },
        ],
      }),
    /legal_target_ids.*sorted/i,
  );
  assert.throws(
    () =>
      parseWithChoices({
        ...choices,
        actions: [
          {
            ...action,
            selectable_target_ids: ["hushglass_sentry", "vela_quill"],
            legal_target_ids: ["hushglass_sentry", "hushglass_sentry"],
            reason: null,
          },
        ],
      }),
    /legal_target_ids.*unique/i,
  );
  assert.throws(
    () =>
      parseWithChoices({
        ...choices,
        actions: [
          {
            ...action,
            legal_target_ids: ["vela_quill"],
            reason: null,
          },
        ],
      }),
    /legal_target_ids.*subset/i,
  );
  assert.throws(
    () =>
      parseWithChoices({
        ...choices,
        actions: [
          {
            ...action,
            legal_target_ids: ["hushglass_sentry"],
            reason: "no_legal_targets",
          },
        ],
      }),
    /reason.*legal targets/i,
  );
  assert.throws(
    () =>
      parseWithChoices({
        ...choices,
        actions: [{ ...action, reason: null }],
      }),
    /reason.*no_legal_targets/i,
  );
  assert.throws(
    () => parseWithChoices({ ...choices, actor_id: "hushglass_sentry" }),
    /choices\.actor_id.*active_actor_id/i,
  );
  assert.throws(
    () =>
      parseWithChoices({
        ...choices,
        movement: { ...choices.movement, origin: [17.5, 12.5, 0] },
      }),
    /choices\.movement\.origin.*actor position/i,
  );
  assert.throws(
    () =>
      parseWithChoices({
        ...choices,
        movement: { ...choices.movement, remaining_ft: 25 },
      }),
    /choices\.movement\.remaining_ft.*actor movement/i,
  );
  assert.throws(
    () => parseWithChoices({ ...choices, reason: "no_available_actions" }),
    /reason.*actions/i,
  );

  assert.doesNotThrow(() =>
    parseSessionView({
      ...sessionView,
      projection: {
        ...sessionView.projection,
        actors: {
          ...sessionView.projection.actors,
          vela_quill: {
            ...sessionView.projection.actors.vela_quill,
            actions: [
              ...sessionView.projection.actors.vela_quill.actions,
              {
                ...sessionView.projection.actors.vela_quill.actions[0],
                action_cost: "bonus",
              },
            ],
          },
        },
      },
    }),
  );
});

test("requires choices exactly while an actor is awaiting declaration", () => {
  assert.throws(
    () =>
      parseSessionView({
        ...sessionView,
        projection: { ...sessionView.projection, choices: null },
      }),
    /choices.*required.*awaiting/i,
  );

  assert.throws(
    () =>
      parseSessionView({
        ...sessionView,
        projection: {
          ...sessionView.projection,
          phase: "terminal",
          outcome: "party_victory",
          winner: "party",
          active_actor_id: null,
          prompt: null,
        },
      }),
    /choices.*null.*terminal/i,
  );
});

test("plans a grid-centered authoritative movement path within the actor budget", () => {
  const scene = parseSessionView(sessionView).scene!;

  assert.deepEqual(cellToFeet(scene, { column: 3, row: 2 }), [
    17.5,
    12.5,
    0,
  ]);
  assert.deepEqual(
    planGridMovement({
      scene,
      start: [12.5, 12.5, 0],
      destination: { column: 3, row: 2 },
      movementRemaining: 30,
    }),
    {
      destination: { column: 3, row: 2 },
      distanceFt: 5,
      end: [17.5, 12.5, 0],
      path: [
        [12.5, 12.5, 0],
        [17.5, 12.5, 0],
      ],
    },
  );
  assert.throws(
    () =>
      planGridMovement({
        scene,
        start: [12.5, 12.5, 0],
        destination: { column: 0, row: 0 },
        movementRemaining: 5,
      }),
    /exceeds.*movement/i,
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

test("builds a reconnect cursor URL and strictly parses streamed events", () => {
  assert.equal(
    vttEventsUrl(17),
    "http://127.0.0.1:8000/api/v1/events?after=17",
  );
  assert.throws(() => vttEventsUrl(-1), /non-negative integer/i);

  const event = {
    schema_version: "vtt.event.v1",
    event_id: "echo-vault-session:2:1",
    session_id: "echo-vault-session",
    sequence: 7,
    revision: 2,
    kind: "dnd.encounter.completed",
    command_id: "turn-1",
    versions: sessionView.versions,
    causation_id: null,
    audience: ["all"],
    payload: { outcome: "party_victory" },
  } as const;

  assert.deepEqual(parseVttEvent(event), event);
  assert.throws(
    () => parseVttEvent({ ...event, canonical_state: { actors: {} } }),
    /unexpected field.*canonical_state/i,
  );
});

test("streams encounter events with bearer auth through fetch", async () => {
  const event = {
    schema_version: "vtt.event.v1",
    event_id: "echo-vault-session:2:1",
    session_id: "echo-vault-session",
    sequence: 7,
    revision: 2,
    kind: "dnd.encounter.completed",
    command_id: "turn-1",
    versions: sessionView.versions,
    causation_id: null,
    audience: ["all"],
    payload: { outcome: "party_victory" },
  } as const;
  const block = [
    "id: 7",
    "event: vtt.event",
    `data: ${JSON.stringify(event)}`,
  ].join("\n");
  assert.deepEqual(parseVttSseBlock(block), event);
  assert.equal(parseVttSseBlock(": heartbeat"), null);

  const originalFetch = globalThis.fetch;
  const encoder = new TextEncoder();
  const received: unknown[] = [];
  let opened = false;
  const eventBlock = `${block}\n\n`;
  globalThis.fetch = (async (input, init) => {
    assert.equal(
      String(input),
      "http://127.0.0.1:8000/api/v1/events?after=3",
    );
    assert.deepEqual(init?.headers, {
      accept: "text/event-stream",
      authorization: "Bearer table-token-1234567890",
    });
    return new Response(
      new ReadableStream({
        start(controller) {
          for (const chunk of [": heartbeat\n\n", eventBlock.slice(0, 19), eventBlock.slice(19)]) {
            controller.enqueue(encoder.encode(chunk));
          }
          controller.close();
        },
      }),
      { status: 200 },
    );
  }) as typeof fetch;
  try {
    const cursor = await streamVttEvents({
      after: 3,
      bearerToken: "table-token-1234567890",
      signal: new AbortController().signal,
      onOpen: () => {
        opened = true;
      },
      onEvent: (incoming) => received.push(incoming),
    });
    assert.equal(opened, true);
    assert.equal(cursor, 7);
    assert.deepEqual(received, [event]);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
