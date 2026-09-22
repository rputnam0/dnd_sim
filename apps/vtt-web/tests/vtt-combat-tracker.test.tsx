import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import TestRenderer, { act } from "react-test-renderer";

import { VttCombatTrackerPanel } from "../app/vtt-combat-tracker-panel";
import {
  buildCombatControlCommand,
  type CombatControlPayload,
} from "../app/vtt-combat-tracker";
import type { ActorProjection, EncounterProjection } from "../app/vtt-client";

const reactTestEnvironment: typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean } = globalThis;
reactTestEnvironment.IS_REACT_ACT_ENVIRONMENT = true;

function actor(actorId: string, name: string, team: string): ActorProjection {
  return {
    actor_id: actorId,
    team,
    name,
    hp: 20,
    max_hp: 20,
    temp_hp: 0,
    ac: 15,
    position: [0, 0, 0],
    movement_remaining: 30,
    conditions: [],
    dead: false,
    stable: false,
    bonus_available: true,
    reaction_available: true,
    actions: [],
  };
}

const projection: EncounterProjection = {
  phase: "awaiting_declaration",
  outcome: null,
  winner: null,
  current_index: 0,
  active_actor_id: "hero",
  round_number: 1,
  max_rounds: 4,
  initiative_order: ["hero", "enemy", "ally"],
  actors: {
    hero: actor("hero", "Hero", "party"),
    enemy: actor("enemy", "Enemy", "enemy"),
    ally: actor("ally", "Ally", "party"),
  },
  prompt: null,
  result: null,
  choices: null,
};

test("builds the exact actor-independent admin tracker command", () => {
  const command = buildCombatControlCommand({
    sessionId: "session-a",
    expectedRevision: 7,
    commandId: "control-a",
    payload: {
      operation: "advance",
      direction: "next",
      reason: "Advance after the table correction.",
    },
  });

  assert.deepEqual(command, {
    schema_version: "vtt.command.v1",
    command_id: "control-a",
    session_id: "session-a",
    actor_id: null,
    expected_revision: 7,
    mode: "admin",
    kind: "dnd.combat.control.v1",
    payload: {
      operation: "advance",
      direction: "next",
      reason: "Advance after the table correction.",
    },
    intent_metadata: { surface: "echo-vault-web" },
  });
  assert.throws(
    () =>
      buildCombatControlCommand({
        sessionId: "session-a",
        expectedRevision: 7,
        payload: {
          operation: "override",
          active_actor_id: "hero",
          round_number: 0,
          reason: "Invalid round.",
        },
      }),
    /round/i,
  );
});

test("mounted GM tracker drives every production control and player view is read-only", async () => {
  const commands: CombatControlPayload[] = [];
  let renderer: TestRenderer.ReactTestRenderer;
  await act(async () => {
    renderer = TestRenderer.create(
      createElement(VttCombatTrackerPanel, {
        projection,
        canManage: true,
        pending: false,
        error: null,
        onControl: async (payload: CombatControlPayload) => {
          commands.push(payload);
        },
      }),
    );
  });
  const root = renderer!.root;
  const reason = root.findByProps({ name: "combat-control-reason" });
  await act(async () => {
    reason.props.onChange({ currentTarget: { value: "Correct the live table." } });
  });
  const button = (name: string) =>
    root
      .findAllByType("button")
      .find((item) => item.children.join("") === name)!;

  await act(async () => button("Previous").props.onClick());
  await act(async () => button("Next").props.onClick());
  await act(async () => button("Move Enemy up").props.onClick());

  const selects = root.findAllByType("select");
  await act(async () => {
    selects[0].props.onChange({ currentTarget: { value: "enemy" } });
  });
  await act(async () => button("Delay turn").props.onClick());
  await act(async () => {
    selects[1].props.onChange({ currentTarget: { value: "ally" } });
    root
      .findByProps({ name: "combat-override-round" })
      .props.onChange({ currentTarget: { value: "3" } });
  });
  await act(async () => button("Apply cursor").props.onClick());

  assert.deepEqual(
    commands.map((command) => command.operation),
    ["advance", "advance", "reorder", "delay", "override"],
  );
  assert.deepEqual(commands[2], {
    operation: "reorder",
    initiative_order: ["enemy", "hero", "ally"],
    reason: "Correct the live table.",
  });
  assert.deepEqual(commands[4], {
    operation: "override",
    active_actor_id: "ally",
    round_number: 3,
    reason: "Correct the live table.",
  });
  await act(async () => renderer!.unmount());

  await act(async () => {
    renderer = TestRenderer.create(
      createElement(VttCombatTrackerPanel, {
        projection,
        canManage: false,
        pending: false,
        error: null,
        onControl: async () => undefined,
      }),
    );
  });
  assert.equal(renderer!.root.findAllByType("button").length, 0);
  assert.match(JSON.stringify(renderer!.toJSON()), /read-only/i);
  await act(async () => renderer!.unmount());
});
