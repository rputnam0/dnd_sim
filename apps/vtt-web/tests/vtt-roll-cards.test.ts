import assert from "node:assert/strict";
import test from "node:test";

import { parseVttRollCard, rollCardFromEvent } from "../app/vtt-roll-cards";

const CARD = {
  schema_version: "vtt.roll_card.v1",
  card_id: "roll:abc",
  roll_sequence: 2,
  source_actor_id: "vela_quill",
  target_actor_id: null,
  action_id: "action:Lattice Lance",
  purpose: "damage",
  fact: {
    schema_version: "vtt.roll_card_damage_fact.v1",
    kind: "damage",
    expression: "1d8+3",
    damage_type: "force",
    faces: [{
      schema_version: "vtt.roll_card_face.v1",
      generation_index: 1,
      sides: 8,
      value: 7,
      status: "kept",
      replacement_generation_index: null,
    }],
    flat_modifier: 3,
    rolled_total: 10,
    raw_damage: 10,
    applied_damage: 5,
    critical: false,
    adjustments: [{
      schema_version: "vtt.roll_card_adjustment.v1",
      stage: "applied",
      kind: "resistance",
      amount: -5,
      generated_face: null,
    }],
  },
};

test("strictly parses only finalized audience-safe roll cards", () => {
  const parsed = parseVttRollCard(CARD);
  assert.equal(parsed.fact.total, 5);
  assert.equal(parsed.fact.faces[0].value, 7);
  assert.equal(parsed.fact.adjustments[0].kind, "resistance");
  assert.throws(() => parseVttRollCard({ ...CARD, audience: ["secret"] }));
  assert.throws(() => parseVttRollCard({
    ...CARD,
    fact: { ...CARD.fact, applied_damage: null },
  }));
  assert.throws(() => parseVttRollCard({
    ...CARD,
    fact: { ...CARD.fact, hidden_modifier_source: "private" },
  }));
});

test("rejects impossible damage stage equations and malformed replacement chains", () => {
  assert.throws(() => parseVttRollCard({
    ...CARD,
    fact: { ...CARD.fact, rolled_total: 999 },
  }));
  assert.throws(() => parseVttRollCard({
    ...CARD,
    fact: {
      ...CARD.fact,
      faces: [{
        ...CARD.fact.faces[0],
        status: "rerolled",
        replacement_generation_index: 2,
      }],
    },
  }));
  assert.throws(() => parseVttRollCard({
    ...CARD,
    fact: { ...CARD.fact, raw_damage: 9 },
  }));
  assert.throws(() => parseVttRollCard({
    ...CARD,
    fact: { ...CARD.fact, applied_damage: 6 },
  }));
});

const D20_CARD = {
  ...CARD,
  card_id: "roll:d20",
  purpose: "attack",
  fact: {
    schema_version: "vtt.roll_card_d20_fact.v1",
    kind: "d20",
    expression: "1d20+2",
    mode: "resolved",
    faces: [{
      schema_version: "vtt.roll_card_face.v1",
      generation_index: 1,
      sides: 20,
      value: 11,
      status: "kept",
      replacement_generation_index: null,
    }, {
      schema_version: "vtt.roll_card_face.v1",
      generation_index: 2,
      sides: 20,
      value: 5,
      status: "discarded",
      replacement_generation_index: null,
    }],
    kept_generation_index: 1,
    flat_modifier: 2,
    total: 11,
    threshold: 12,
    outcome: "miss",
    critical: false,
    adjustments: [{
      schema_version: "vtt.roll_card_adjustment.v1",
      stage: "total",
      kind: "cutting_words",
      amount: -2,
      generated_face: {
        schema_version: "vtt.roll_card_face.v1",
        generation_index: 1,
        sides: 6,
        value: 2,
        status: "kept",
        replacement_generation_index: null,
      },
    }],
  },
};

test("validates d20 kept face, mode, totals, outcomes, and replacement links", () => {
  assert.equal(parseVttRollCard(D20_CARD).fact.total, 11);
  for (const fact of [
    { ...D20_CARD.fact, kept_generation_index: 2 },
    { ...D20_CARD.fact, mode: "normal" },
    { ...D20_CARD.fact, total: 12 },
    { ...D20_CARD.fact, outcome: "hit" },
    {
      ...D20_CARD.fact,
      faces: D20_CARD.fact.faces.map((item, index) => index === 0
        ? { ...item, status: "replaced", replacement_generation_index: 3 }
        : item),
    },
  ]) {
    assert.throws(() => parseVttRollCard({ ...D20_CARD, fact }));
  }
});

test("validates saving throw totals and DC outcomes", () => {
  const save = {
    ...CARD,
    card_id: "roll:save",
    purpose: "saving_throw",
    fact: {
      schema_version: "vtt.roll_card_save_fact.v1",
      kind: "saving_throw",
      ability: "dexterity",
      expression: "1d20+2",
      mode: "normal",
      faces: [{
        schema_version: "vtt.roll_card_face.v1",
        generation_index: 1,
        sides: 20,
        value: 11,
        status: "kept",
        replacement_generation_index: null,
      }],
      kept_generation_index: 1,
      flat_modifier: 2,
      total: 13,
      dc: 12,
      succeeded: true,
    },
  };
  assert.equal(parseVttRollCard(save).fact.outcome, "success");
  assert.throws(() => parseVttRollCard({
    ...save,
    fact: { ...save.fact, total: 14 },
  }));
  assert.throws(() => parseVttRollCard({
    ...save,
    fact: { ...save.fact, succeeded: false },
  }));
});

test("extracts a card only from the exact projected event envelope", () => {
  const event = {
    schema_version: "vtt.event_draft.v1" as const,
    kind: "vtt.roll.card.v1",
    audience: ["all"],
    payload: { card: CARD },
  };
  assert.equal(rollCardFromEvent(event)?.card_id, "roll:abc");
  assert.throws(() => rollCardFromEvent({
    ...event,
    payload: { card: CARD, raw_record: { audience: ["gm_only"] } },
  }));
  assert.equal(rollCardFromEvent({ ...event, kind: "dnd.turn.resolved" }), null);
});

test("parses finalized healing and rejects inconsistent overheal", () => {
  const healing = {
    ...CARD,
    card_id: "roll:healing",
    purpose: "healing",
    fact: {
      schema_version: "vtt.roll_card_healing_fact.v1",
      kind: "healing",
      expression: "1d4+3",
      faces: [{
        schema_version: "vtt.roll_card_face.v1",
        generation_index: 1,
        sides: 4,
        value: 4,
        status: "kept",
        replacement_generation_index: null,
      }],
      flat_modifier: 3,
      rolled_healing: 7,
      effective_healing: 2,
      overheal: 5,
    },
  };

  const parsed = parseVttRollCard(healing);
  assert.equal(parsed.fact.total, 2);
  assert.equal(parsed.fact.effective_healing, 2);
  assert.equal(parsed.fact.overheal, 5);
  assert.throws(() => parseVttRollCard({
    ...healing,
    fact: { ...healing.fact, overheal: 4 },
  }));
  assert.throws(() => parseVttRollCard({
    ...healing,
    fact: { ...healing.fact, source: "hidden" },
  }));
});
