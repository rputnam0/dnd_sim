import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import TestRenderer, { act, type ReactTestInstance } from "react-test-renderer";
import AdventurePlay from "../app/adventure-play";
import { adventureFixture, encounter, receipt } from "./adventure-fixtures";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
function button(root: ReactTestInstance, label: string) {
  return root.findAllByType("button").find((node) => content(node).includes(label))!;
}
function content(node: ReactTestInstance | string): string { return typeof node === "string" ? node : node.children.map(content).join(""); }
function rendered(renderer: TestRenderer.ReactTestRenderer) { return JSON.stringify(renderer.toJSON()); }

test("loads the saved adventure, renders shared tabletop and commits a story choice once", async (context) => {
  const view = adventureFixture();
  const commands: Record<string, unknown>[] = [];
  context.mock.method(globalThis, "fetch", async (_url: unknown, init?: RequestInit) => {
    if (init?.method === "POST") {
      const command = JSON.parse(init.body as string); commands.push(command); view.revision++;
      view.location.name = "Keeper’s hall";
      return Response.json(receipt(command.command_id));
    }
    return Response.json(view);
  });
  let renderer!: TestRenderer.ReactTestRenderer;
  await act(async () => { renderer = TestRenderer.create(createElement(AdventurePlay)); });
  assert.match(rendered(renderer), /The Lantern Below/);
  assert.match(rendered(renderer), /Healing draught/);
  assert.match(rendered(renderer), /The fading beacon/);
  assert.equal(renderer.root.findAllByProps({ className: "map-panel" }).length, 1);
  await act(async () => {
    const enter = button(renderer.root, "Enter the keeper");
    enter.props.onClick(); enter.props.onClick();
  });
  assert.equal(commands.length, 1);
  assert.deepEqual(commands[0].payload, { choice_id: "enter" });
  assert.equal(commands[0].mode, "commit");
  assert.match(rendered(renderer), /Keeper’s hall/);
  await act(async () => renderer.unmount());
});

test("uncertain saves lock choices and retry exactly the same command", async (context) => {
  const commands: unknown[] = [];
  context.mock.method(globalThis, "fetch", async (_url: unknown, init?: RequestInit) => {
    if (init?.method !== "POST") return Response.json(adventureFixture());
    const command = JSON.parse(init.body as string); commands.push(command);
    if (commands.length === 1) throw new Error("Connection lost");
    return Response.json(receipt(command.command_id));
  });
  let renderer!: TestRenderer.ReactTestRenderer;
  await act(async () => { renderer = TestRenderer.create(createElement(AdventurePlay)); });
  await act(async () => button(renderer.root, "Enter the keeper").props.onClick());
  assert.equal(button(renderer.root, "Enter the keeper").props.disabled, true);
  assert.match(rendered(renderer), /Connection lost/);
  await act(async () => button(renderer.root, "Retry saved action").props.onClick());
  assert.deepEqual(commands[0], commands[1]);
  await act(async () => renderer.unmount());
});

test("stale commands reload current state without silently replaying the player's choice", async (context) => {
  let reads = 0;
  context.mock.method(globalThis, "fetch", async (_url: unknown, init?: RequestInit) => {
    if (init?.method === "POST") return Response.json({ schema_version: "vtt.error.v1", code: "revision_conflict", message: "The adventure changed.", details: {} }, { status: 409 });
    const view = adventureFixture(); view.revision = reads++;
    if (reads > 1) view.objective = "A refreshed objective";
    return Response.json(view);
  });
  let renderer!: TestRenderer.ReactTestRenderer;
  await act(async () => { renderer = TestRenderer.create(createElement(AdventurePlay)); });
  await act(async () => button(renderer.root, "Enter the keeper").props.onClick());
  assert.match(rendered(renderer), /A refreshed objective/);
  assert.equal(reads, 2);
  await act(async () => renderer.unmount());
});

test("combat submits selected movement, action and target with no preview request", async (context) => {
  const view = adventureFixture(); view.phase = "combat"; view.combat = encounter; view.choices = [];
  view.journal.push({ id: "combat_wardens_turn-0", title: "Combat · Warden", text: "The warden’s blade misses Mara." });
  const commands: Record<string, unknown>[] = [];
  context.mock.method(globalThis, "fetch", async (_url: unknown, init?: RequestInit) => {
    if (init?.method !== "POST") return Response.json(view);
    const command = JSON.parse(init.body as string); commands.push(command);
    return Response.json(receipt(command.command_id));
  });
  let renderer!: TestRenderer.ReactTestRenderer;
  await act(async () => { renderer = TestRenderer.create(createElement(AdventurePlay)); });
  assert.match(content(renderer.root), /Mara’s turn/);
  assert.equal(content(renderer.root.findByProps({ "aria-label": "Last exchange" })), "Last exchangeThe warden’s blade misses Mara.");
  const cell = renderer.root.findAllByProps({ role: "gridcell" }).find((node) => node.props["aria-label"].startsWith("Cell C2,"))!;
  await act(async () => cell.props.onClick());
  await act(async () => renderer.root.findByProps({ "aria-label": "Target" }).props.onChange({ target: { value: "warden" } }));
  await act(async () => button(renderer.root, "Take turn").props.onClick());
  assert.equal(commands.length, 1);
  assert.equal(commands[0].kind, "dnd.declare_turn.v1");
  assert.equal(commands[0].mode, "commit");
  const payload = commands[0].payload as { movement_path: unknown[]; action: { action_name: string; targets: unknown[] } };
  assert.equal(payload.action.action_name, "Longsword");
  assert.deepEqual(payload.action.targets, [{ actor_id: "warden" }]);
  assert.deepEqual(payload.movement_path, [[7.5, 7.5, 0], [7.5, 12.5, 0]]);
  await act(async () => renderer.unmount());
});

test("failed initial load reconnects to the backend save", async (context) => {
  let reads = 0;
  context.mock.method(globalThis, "fetch", async () => {
    if (reads++ === 0) throw new Error("Backend unavailable");
    const view = adventureFixture(); view.revision = 18; view.objective = "Resume at the beacon";
    return Response.json(view);
  });
  let renderer!: TestRenderer.ReactTestRenderer;
  await act(async () => { renderer = TestRenderer.create(createElement(AdventurePlay)); });
  assert.match(content(renderer.root), /Backend unavailable/);
  await act(async () => button(renderer.root, "Reconnect").props.onClick());
  assert.match(content(renderer.root), /Resume at the beacon/);
  assert.equal(reads, 2);
  await act(async () => renderer.unmount());
});

test("combat can include the party's available bonus action in the same committed turn", async (context) => {
  const view = adventureFixture(); view.phase = "combat"; view.choices = [];
  view.combat = structuredClone(encounter);
  view.combat.actors.mara.actions.push({ name: "Second wind", action_type: "utility", action_cost: "bonus", target_mode: "self", reach_ft: null, range_normal_ft: null, range_long_ft: null });
  view.combat.choices!.actions.push({ action_name: "Second wind", action_cost: "bonus", target_mode: "self", requires_explicit_targets: false, selectable_target_ids: ["mara"], legal_target_ids: ["mara"], reason: null });
  let payload: Record<string, unknown> | null = null;
  context.mock.method(globalThis, "fetch", async (_url: unknown, init?: RequestInit) => {
    if (init?.method !== "POST") return Response.json(view);
    const command = JSON.parse(init.body as string); payload = command.payload;
    return Response.json(receipt(command.command_id));
  });
  let renderer!: TestRenderer.ReactTestRenderer;
  await act(async () => { renderer = TestRenderer.create(createElement(AdventurePlay)); });
  await act(async () => renderer.root.findByProps({ "aria-label": "Target" }).props.onChange({ target: { value: "warden" } }));
  await act(async () => renderer.root.findByProps({ "aria-label": "Bonus action" }).props.onChange({ target: { value: "Second wind" } }));
  await act(async () => button(renderer.root, "Take turn").props.onClick());
  assert.deepEqual(payload && payload["bonus_action"], { action_name: "Second wind", targets: [], resource_spend: { amounts: {} }, spell_slot_level: null, rationale: {} });
  await act(async () => renderer.unmount());
});

test("saved command followed by failed reload reconnects without sending it again", async (context) => {
  let reads = 0;
  let posts = 0;
  context.mock.method(globalThis, "fetch", async (_url: unknown, init?: RequestInit) => {
    if (init?.method === "POST") {
      posts++; return Response.json(receipt(JSON.parse(init.body as string).command_id));
    }
    if (++reads === 2) throw new Error("Read interrupted");
    const view = adventureFixture(); view.revision = posts;
    return Response.json(view);
  });
  let renderer!: TestRenderer.ReactTestRenderer;
  await act(async () => { renderer = TestRenderer.create(createElement(AdventurePlay)); });
  await act(async () => button(renderer.root, "Enter the keeper").props.onClick());
  assert.match(content(renderer.root), /Your action was saved/);
  assert.equal(button(renderer.root, "Enter the keeper").props.disabled, true);
  await act(async () => button(renderer.root, "Reconnect").props.onClick());
  assert.equal(posts, 1);
  assert.equal(button(renderer.root, "Enter the keeper").props.disabled, false);
  await act(async () => renderer.unmount());
});

test("finished adventures show their ending and require explicit restart confirmation", async (context) => {
  const view = adventureFixture(); view.phase = "complete";
  view.ending = { title: "A light returns", text: "The harbor sees another dawn." };
  view.choices = [{ id: "restart", label: "New adventure", description: "Begin again." }];
  let posts = 0;
  context.mock.method(globalThis, "fetch", async (_url: unknown, init?: RequestInit) => {
    if (init?.method !== "POST") return Response.json(view);
    posts++; return Response.json(receipt(JSON.parse(init.body as string).command_id));
  });
  let renderer!: TestRenderer.ReactTestRenderer;
  await act(async () => { renderer = TestRenderer.create(createElement(AdventurePlay)); });
  assert.match(rendered(renderer), /A light returns/);
  await act(async () => button(renderer.root, "New adventure").props.onClick());
  assert.equal(posts, 0);
  assert.equal(renderer.root.findAllByProps({ role: "alertdialog" }).length, 1);
  await act(async () => button(renderer.root, "Keep this adventure").props.onClick());
  assert.equal(posts, 0);
  await act(async () => button(renderer.root, "New adventure").props.onClick());
  await act(async () => button(renderer.root, "Start new adventure").props.onClick());
  assert.equal(posts, 1);
  await act(async () => renderer.unmount());
});
