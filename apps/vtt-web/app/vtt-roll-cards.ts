import type { DisplayEvent, JsonValue } from "./vtt-client";

export interface RollCardFace {
  schema_version: "vtt.roll_card_face.v1";
  generation_index: number;
  sides: number;
  value: number;
  status: "kept" | "discarded" | "rerolled" | "replaced";
  replacement_generation_index: number | null;
}

export interface RollCardAdjustment {
  schema_version: "vtt.roll_card_adjustment.v1";
  stage: "total" | "threshold" | "raw" | "applied";
  kind: "bardic_inspiration" | "cutting_words" | "shield" | "guided_strike" | "war_gods_blessing" | "floor" | "bonus" | "reduction" | "resistance" | "vulnerability" | "immunity" | "absorption" | "other";
  amount: number;
  generated_face: RollCardFace | null;
}

export interface RollCardFact {
  schema_version: string;
  kind: "d20" | "saving_throw" | "damage" | "healing";
  expression: string;
  faces: RollCardFace[];
  total: number;
  outcome: string;
  critical: boolean;
  damage_type: string | null;
  raw_damage: number | null;
  applied_damage: number | null;
  rolled_healing: number | null;
  effective_healing: number | null;
  overheal: number | null;
  adjustments: RollCardAdjustment[];
}

export interface VttRollCard {
  schema_version: "vtt.roll_card.v1";
  card_id: string;
  roll_sequence: number;
  source_actor_id: string | null;
  target_actor_id: string | null;
  action_id: string | null;
  purpose: string;
  fact: RollCardFact;
}

type ObjectValue = Record<string, unknown>;

function exactObject(value: unknown, keys: readonly string[], path: string): ObjectValue {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`${path} must be an object`);
  }
  const result = value as ObjectValue;
  const expected = new Set(keys);
  if (Object.keys(result).some((key) => !expected.has(key))) {
    throw new Error(`${path} contains unexpected fields`);
  }
  if (keys.some((key) => !(key in result))) throw new Error(`${path} is incomplete`);
  return result;
}

function text(value: unknown, path: string): string {
  if (typeof value !== "string" || !value || value.trim() !== value || value.length > 256) {
    throw new Error(`${path} must be canonical text`);
  }
  return value;
}

function optionalText(value: unknown, path: string): string | null {
  return value === null ? null : text(value, path);
}

function integer(value: unknown, path: string, minimum?: number): number {
  if (!Number.isSafeInteger(value) || (minimum !== undefined && (value as number) < minimum)) {
    throw new Error(`${path} must be a bounded integer`);
  }
  return value as number;
}

function booleanValue(value: unknown, path: string): boolean {
  if (typeof value !== "boolean") throw new Error(`${path} must be a boolean`);
  return value;
}

function literal<T extends string>(value: unknown, allowed: readonly T[], path: string): T {
  if (typeof value !== "string" || !allowed.includes(value as T)) {
    throw new Error(`${path} is unsupported`);
  }
  return value as T;
}

function face(value: unknown, index: number, pathPrefix = "roll_card.fact.faces"): RollCardFace {
  const path = `${pathPrefix}[${index}]`;
  const data = exactObject(value, [
    "schema_version", "generation_index", "sides", "value", "status",
    "replacement_generation_index",
  ], path);
  const sides = integer(data.sides, `${path}.sides`, 2);
  const faceValue = integer(data.value, `${path}.value`, 1);
  if (faceValue > sides) throw new Error(`${path}.value exceeds its die`);
  return {
    schema_version: literal(data.schema_version, ["vtt.roll_card_face.v1"], `${path}.schema_version`),
    generation_index: integer(data.generation_index, `${path}.generation_index`, 1),
    sides,
    value: faceValue,
    status: literal(data.status, ["kept", "discarded", "rerolled", "replaced"], `${path}.status`),
    replacement_generation_index: data.replacement_generation_index === null
      ? null
      : integer(data.replacement_generation_index, `${path}.replacement_generation_index`, 1),
  };
}

function faces(value: unknown): RollCardFace[] {
  if (!Array.isArray(value) || value.length > 64) throw new Error("roll_card faces exceed bounds");
  const parsed = value.map((value, index) => face(value, index));
  if (parsed.some((item, index) => item.generation_index !== index + 1)) {
    throw new Error("roll_card faces must preserve generation order");
  }
  return parsed;
}

function validateGeneratedFaces(parsed: RollCardFace[], path: string): void {
  const byGeneration = new Map(parsed.map((item) => [item.generation_index, item]));
  for (const item of parsed) {
    const superseded = item.status === "rerolled" || item.status === "replaced";
    if (superseded !== (item.replacement_generation_index !== null)) {
      throw new Error(`${path} replacement status is inconsistent`);
    }
    if (item.replacement_generation_index === null) continue;
    if (item.replacement_generation_index <= item.generation_index) {
      throw new Error(`${path} replacement must refer to a later face`);
    }
    const replacement = byGeneration.get(item.replacement_generation_index);
    if (!replacement || replacement.sides !== item.sides) {
      throw new Error(`${path} replacement must identify a same-sided generated face`);
    }
  }
}

function validateD20Resolution(
  parsed: RollCardFace[],
  mode: "normal" | "advantage" | "disadvantage" | "resolved",
  keptGenerationIndex: number,
  flatModifier: number,
  totalAdjustments: RollCardAdjustment[],
  total: number,
): RollCardFace {
  if (parsed.length === 0 || parsed.some((item) => item.sides !== 20)) {
    throw new Error("roll_card d20 resolution requires d20 faces");
  }
  validateGeneratedFaces(parsed, "roll_card.fact.faces");
  const kept = parsed.filter((item) => item.status === "kept");
  if (kept.length !== 1 || kept[0].generation_index !== keptGenerationIndex) {
    throw new Error("roll_card kept_generation_index must identify the only kept face");
  }
  const candidates = parsed.filter((item) => item.status === "kept" || item.status === "discarded");
  if (mode === "normal" && candidates.length !== 1) {
    throw new Error("roll_card normal mode requires one final candidate");
  }
  if ((mode === "advantage" || mode === "disadvantage") && candidates.length < 2) {
    throw new Error(`roll_card ${mode} requires at least two final candidates`);
  }
  const candidateValues = candidates.map((item) => item.value);
  if (mode === "advantage" && kept[0].value !== Math.max(...candidateValues)) {
    throw new Error("roll_card advantage kept the wrong face");
  }
  if (mode === "disadvantage" && kept[0].value !== Math.min(...candidateValues)) {
    throw new Error("roll_card disadvantage kept the wrong face");
  }
  const expectedTotal = kept[0].value + flatModifier + totalAdjustments
    .filter((item) => item.stage === "total")
    .reduce((sum, item) => sum + item.amount, 0);
  if (total !== expectedTotal) throw new Error("roll_card d20 total does not match its facts");
  return kept[0];
}

function adjustment(value: unknown, index: number): RollCardAdjustment {
  const path = `roll_card.fact.adjustments[${index}]`;
  const data = exactObject(value, [
    "schema_version", "stage", "kind", "amount", "generated_face",
  ], path);
  const amount = integer(data.amount, `${path}.amount`);
  if (amount === 0) throw new Error(`${path}.amount must be non-zero`);
  const generatedFace = data.generated_face === null
    ? null
    : face(data.generated_face, 0, `${path}.generated_face`);
  if (generatedFace !== null && (
    generatedFace.status !== "kept" || generatedFace.replacement_generation_index !== null
  )) {
    throw new Error(`${path}.generated_face must be a final kept face`);
  }
  return {
    schema_version: literal(data.schema_version, ["vtt.roll_card_adjustment.v1"], `${path}.schema_version`),
    stage: literal(data.stage, ["total", "threshold", "raw", "applied"], `${path}.stage`),
    kind: literal(data.kind, ["bardic_inspiration", "cutting_words", "shield", "guided_strike", "war_gods_blessing", "floor", "bonus", "reduction", "resistance", "vulnerability", "immunity", "absorption", "other"], `${path}.kind`),
    amount,
    generated_face: generatedFace,
  };
}

function validateAdjustmentFaces(adjustments: RollCardAdjustment[]): void {
  const generated = adjustments
    .map((item) => item.generated_face)
    .filter((item): item is RollCardFace => item !== null);
  if (generated.some((item, index) => item.generation_index !== index + 1)) {
    throw new Error("roll_card modifier dice must preserve generation order");
  }
}

function parseFact(value: unknown): RollCardFact {
  const base = value as ObjectValue;
  const kind = literal(base?.kind, ["d20", "saving_throw", "damage", "healing"], "roll_card.fact.kind");
  if (kind === "healing") {
    const data = exactObject(value, [
      "schema_version", "kind", "expression", "faces", "flat_modifier",
      "rolled_healing", "effective_healing", "overheal",
    ], "roll_card.fact");
    const parsedFaces = faces(data.faces);
    validateGeneratedFaces(parsedFaces, "roll_card.fact.faces");
    const flatModifier = integer(data.flat_modifier, "roll_card.fact.flat_modifier");
    const rolledHealing = integer(data.rolled_healing, "roll_card.fact.rolled_healing", 0);
    const effectiveHealing = integer(data.effective_healing, "roll_card.fact.effective_healing", 0);
    const overheal = integer(data.overheal, "roll_card.fact.overheal", 0);
    const keptTotal = parsedFaces
      .filter((item) => item.status === "kept")
      .reduce((total, item) => total + item.value, 0);
    if (rolledHealing !== keptTotal + flatModifier) {
      throw new Error("roll_card healing does not match its kept faces");
    }
    if (rolledHealing !== effectiveHealing + overheal) {
      throw new Error("roll_card healing does not match effective healing plus overheal");
    }
    return {
      schema_version: literal(data.schema_version, ["vtt.roll_card_healing_fact.v1"], "roll_card.fact.schema_version"),
      kind,
      expression: text(data.expression, "roll_card.fact.expression"),
      faces: parsedFaces,
      total: effectiveHealing,
      outcome: "healing",
      critical: false,
      damage_type: null,
      raw_damage: null,
      applied_damage: null,
      rolled_healing: rolledHealing,
      effective_healing: effectiveHealing,
      overheal,
      adjustments: [],
    };
  }
  if (kind === "damage") {
    const data = exactObject(value, [
      "schema_version", "kind", "expression", "damage_type", "faces", "flat_modifier",
      "rolled_total", "raw_damage", "applied_damage", "critical", "adjustments",
    ], "roll_card.fact");
    if (!Array.isArray(data.adjustments) || data.adjustments.length > 64) {
      throw new Error("roll_card adjustments exceed bounds");
    }
    const parsedFaces = faces(data.faces);
    validateGeneratedFaces(parsedFaces, "roll_card.fact.faces");
    const flatModifier = integer(data.flat_modifier, "roll_card.fact.flat_modifier");
    const rolledTotal = integer(data.rolled_total, "roll_card.fact.rolled_total");
    const rawDamage = integer(data.raw_damage, "roll_card.fact.raw_damage", 0);
    const appliedDamage = integer(data.applied_damage, "roll_card.fact.applied_damage", 0);
    const parsedAdjustments = data.adjustments.map(adjustment);
    validateAdjustmentFaces(parsedAdjustments);
    if (parsedAdjustments.some((item) => !["raw", "applied"].includes(item.stage))) {
      throw new Error("roll_card damage contains a non-damage adjustment stage");
    }
    const keptTotal = parsedFaces
      .filter((item) => item.status === "kept")
      .reduce((sum, item) => sum + item.value, 0);
    if (rolledTotal !== keptTotal + flatModifier) {
      throw new Error("roll_card damage rolled total does not match its kept faces");
    }
    const rawDelta = parsedAdjustments
      .filter((item) => item.stage === "raw")
      .reduce((sum, item) => sum + item.amount, 0);
    if (rawDamage !== rolledTotal + rawDelta) {
      throw new Error("roll_card raw damage does not match its adjustments");
    }
    const appliedDelta = parsedAdjustments
      .filter((item) => item.stage === "applied")
      .reduce((sum, item) => sum + item.amount, 0);
    if (appliedDamage !== rawDamage + appliedDelta) {
      throw new Error("roll_card applied damage does not match its adjustments");
    }
    return {
      schema_version: literal(data.schema_version, ["vtt.roll_card_damage_fact.v1"], "roll_card.fact.schema_version"),
      kind,
      expression: text(data.expression, "roll_card.fact.expression"),
      faces: parsedFaces,
      total: appliedDamage,
      outcome: "damage",
      critical: booleanValue(data.critical, "roll_card.fact.critical"),
      damage_type: optionalText(data.damage_type, "roll_card.fact.damage_type"),
      raw_damage: rawDamage,
      applied_damage: appliedDamage,
      rolled_healing: null,
      effective_healing: null,
      overheal: null,
      adjustments: parsedAdjustments,
    };
  }
  const save = kind === "saving_throw";
  const keys = save
    ? ["schema_version", "kind", "ability", "expression", "mode", "faces", "kept_generation_index", "flat_modifier", "total", "dc", "succeeded"]
    : ["schema_version", "kind", "expression", "mode", "faces", "kept_generation_index", "flat_modifier", "total", "threshold", "outcome", "critical", "adjustments"];
  const data = exactObject(value, keys, "roll_card.fact");
  const mode = literal(data.mode, ["normal", "advantage", "disadvantage", "resolved"], "roll_card.fact.mode");
  if (save && mode === "resolved") throw new Error("roll_card saving throw mode is unsupported");
  const keptGenerationIndex = integer(data.kept_generation_index, "roll_card.fact.kept_generation_index", 1);
  const flatModifier = integer(data.flat_modifier, "roll_card.fact.flat_modifier");
  const parsedFaces = faces(data.faces);
  const parsedAdjustments = save
    ? []
    : (() => {
        if (!Array.isArray(data.adjustments) || data.adjustments.length > 64) {
          throw new Error("roll_card adjustments exceed bounds");
        }
        const result = data.adjustments.map(adjustment);
        validateAdjustmentFaces(result);
        if (result.some((item) => !["total", "threshold"].includes(item.stage))) {
          throw new Error("roll_card d20 contains a non-d20 adjustment stage");
        }
        return result;
      })();
  const total = integer(data.total, "roll_card.fact.total");
  const kept = validateD20Resolution(
    parsedFaces,
    mode,
    keptGenerationIndex,
    flatModifier,
    parsedAdjustments,
    total,
  );
  if (save) {
    literal(data.ability, ["strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"], "roll_card.fact.ability");
    integer(data.dc, "roll_card.fact.dc", 0);
  } else if (data.threshold !== null) {
    integer(data.threshold, "roll_card.fact.threshold");
  }
  const succeeded = save
    ? booleanValue(data.succeeded, "roll_card.fact.succeeded")
    : false;
  const critical = save
    ? false
    : booleanValue(data.critical, "roll_card.fact.critical");
  const threshold = save ? null : data.threshold as number | null;
  const parsedOutcome = save
    ? (succeeded ? "success" : "failure")
    : literal(data.outcome, ["hit", "miss", "success", "failure", "none"], "roll_card.fact.outcome");
  if (save) {
    if (succeeded !== (total >= (data.dc as number))) {
      throw new Error("roll_card saving throw outcome does not match its DC");
    }
  } else {
    if ((parsedOutcome === "none") !== (threshold === null)) {
      throw new Error("roll_card threshold must match its outcome");
    }
    if (threshold !== null) {
      const expected = parsedOutcome === "hit" || parsedOutcome === "miss"
        ? (kept.value === 20 || (kept.value !== 1 && total >= threshold) ? "hit" : "miss")
        : (total >= threshold ? "success" : "failure");
      if (parsedOutcome !== expected) {
        throw new Error("roll_card d20 outcome does not match its threshold");
      }
    }
    if (critical && parsedOutcome !== "hit") {
      throw new Error("roll_card critical result must be a hit");
    }
  }
  return {
    schema_version: literal(data.schema_version, [save ? "vtt.roll_card_save_fact.v1" : "vtt.roll_card_d20_fact.v1"], "roll_card.fact.schema_version"),
    kind,
    expression: text(data.expression, "roll_card.fact.expression"),
    faces: parsedFaces,
    total,
    outcome: parsedOutcome,
    critical,
    damage_type: null,
    raw_damage: null,
    applied_damage: null,
    rolled_healing: null,
    effective_healing: null,
    overheal: null,
    adjustments: parsedAdjustments,
  };
}

export function parseVttRollCard(value: unknown): VttRollCard {
  const data = exactObject(value, [
    "schema_version", "card_id", "roll_sequence", "source_actor_id",
    "target_actor_id", "action_id", "purpose", "fact",
  ], "roll_card");
  return {
    schema_version: literal(data.schema_version, ["vtt.roll_card.v1"], "roll_card.schema_version"),
    card_id: text(data.card_id, "roll_card.card_id"),
    roll_sequence: integer(data.roll_sequence, "roll_card.roll_sequence", 1),
    source_actor_id: optionalText(data.source_actor_id, "roll_card.source_actor_id"),
    target_actor_id: optionalText(data.target_actor_id, "roll_card.target_actor_id"),
    action_id: optionalText(data.action_id, "roll_card.action_id"),
    purpose: text(data.purpose, "roll_card.purpose"),
    fact: parseFact(data.fact),
  };
}

export function rollCardFromEvent(event: DisplayEvent): VttRollCard | null {
  if (event.kind !== "vtt.roll.card.v1") return null;
  const payload = exactObject(event.payload as JsonValue, ["card"], "roll_event.payload");
  return parseVttRollCard(payload.card);
}
