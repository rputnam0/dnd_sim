import assert from "node:assert/strict";
import test from "node:test";
import { buildAdventureChoice, parseAdventureView, postAdventureCommand } from "../app/adventure-client";
import { adventureFixture, encounter, receipt } from "./adventure-fixtures";

test("adventure projection strictly validates nested content and combat", () => {
  const fixture = adventureFixture();
  assert.equal(parseAdventureView(fixture).party[0].name, "Mara");
  assert.throws(() => parseAdventureView({ ...fixture, arbitrary_flag: true }), /unexpected/);
  assert.throws(() => parseAdventureView({ ...fixture, inventory: [{ ...fixture.inventory[0], quantity: -1 }] }), /quantity/);
  assert.throws(() => parseAdventureView({ ...fixture, phase: "combat" }), /combat/);
  assert.throws(() => parseAdventureView({ ...fixture, choices: [fixture.choices[0], fixture.choices[0]] }), /unique/);
  assert.equal(parseAdventureView({ ...fixture, phase: "combat", combat: encounter }).combat?.active_actor_id, "mara");
});

test("narrative commands contain only the chosen choice and commit directly", () => {
  const view = parseAdventureView(adventureFixture());
  const command = buildAdventureChoice(view, "enter", "command-1");
  assert.deepEqual(command.payload, { choice_id: "enter" });
  assert.equal(command.mode, "commit");
  assert.equal(command.expected_revision, 0);
  assert.throws(() => buildAdventureChoice(view, "forged"), /available/);
});

test("command receipt must match the submitted session and command", async (context) => {
  const command = buildAdventureChoice(parseAdventureView(adventureFixture()), "enter", "command-1");
  context.mock.method(globalThis, "fetch", async () => Response.json(receipt("other-command")));
  await assert.rejects(() => postAdventureCommand(command), /receipt/);
});
