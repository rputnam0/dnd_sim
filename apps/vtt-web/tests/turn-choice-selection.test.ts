import assert from "node:assert/strict";
import test from "node:test";

import {
  initialTurnSelection,
  selectedTargetIdsForChoice,
} from "../app/turn-choice-selection";
import type { TurnActionChoice, TurnChoices } from "../app/vtt-client";

const choices: TurnChoices = {
  schema_version: "dnd.turn-choices.v1",
  actor_id: "vela_quill",
  movement: { origin: [12.5, 12.5, 0], remaining_ft: 30 },
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
};

test("initializes from structural server candidates even when movement is required", () => {
  assert.deepEqual(initialTurnSelection(choices), {
    actionName: "Lattice Lance",
    targetId: "hushglass_sentry",
  });
});

test("emits only selected server candidates for explicit-target actions", () => {
  const choice = choices.actions[0];

  assert.deepEqual(
    selectedTargetIdsForChoice(choice, "hushglass_sentry"),
    ["hushglass_sentry"],
  );
  assert.deepEqual(selectedTargetIdsForChoice(choice, "vela_quill"), []);
  assert.deepEqual(selectedTargetIdsForChoice(choice, null), []);
});

test("keeps targetless and self-resolving modes targetless in declarations", () => {
  const selfChoice = {
    ...choices.actions[0],
    action_name: "Focus",
    target_mode: "self",
    requires_explicit_targets: false,
    selectable_target_ids: ["vela_quill"],
    legal_target_ids: ["vela_quill"],
    reason: null,
  } satisfies TurnActionChoice;

  assert.deepEqual(selectedTargetIdsForChoice(selfChoice, "vela_quill"), []);
});

test("reports an empty selection when no actions are available", () => {
  assert.deepEqual(
    initialTurnSelection({
      ...choices,
      actions: [],
      reason: "no_available_actions",
    }),
    { actionName: "", targetId: null },
  );
});

test("skips an explicit action with no structural candidates when a usable action follows", () => {
  assert.deepEqual(
    initialTurnSelection({
      ...choices,
      actions: [
        {
          ...choices.actions[0],
          selectable_target_ids: [],
        },
        {
          ...choices.actions[0],
          action_name: "Vanish",
          target_mode: "self",
          requires_explicit_targets: false,
          selectable_target_ids: ["vela_quill"],
          legal_target_ids: ["vela_quill"],
          reason: null,
        },
      ],
    }),
    { actionName: "Vanish", targetId: null },
  );
});
