import type { ActorProjection, EncounterProjection } from "../app/vtt-client";

export const hero: ActorProjection = {
  actor_id: "mara", name: "Mara", team: "party", hp: 24, max_hp: 28,
  temp_hp: 0, ac: 16, position: [7.5, 7.5, 0], movement_remaining: 30,
  conditions: [], dead: false, stable: false, bonus_available: true,
  reaction_available: true,
  actions: [{ name: "Longsword", action_type: "attack", action_cost: "action",
    target_mode: "single_enemy", reach_ft: 5, range_normal_ft: null, range_long_ft: null }],
};
export const enemy: ActorProjection = { ...hero, actor_id: "warden", name: "Warden", team: "enemy", position: [12.5, 7.5, 0] };
export const encounter: EncounterProjection = {
  phase: "awaiting_declaration", outcome: null, winner: null, current_index: 0,
  active_actor_id: "mara", round_number: 1, max_rounds: 30,
  initiative_order: ["mara", "warden"], actors: { mara: hero, warden: enemy },
  prompt: { actor_id: "mara", round_number: 1, turn_token: "turn-1" }, result: null,
  choices: { schema_version: "dnd.turn-choices.v1", actor_id: "mara",
    movement: { origin: hero.position, remaining_ft: 30 }, reason: null,
    actions: [{ action_name: "Longsword", action_cost: "action", target_mode: "single_enemy",
      requires_explicit_targets: true, selectable_target_ids: ["warden"], legal_target_ids: ["warden"], reason: null }] },
};
export function adventureFixture() {
  return {
    schema_version: "adventure.view.v1", session_id: "lantern-test", revision: 0,
    versions: { schema_version: "vtt.version_info.v1", engine: "engine@1", rules: "rules@1", content: "lantern@1" },
    title: "The Lantern Below", subtitle: "An adventure for three companions", phase: "exploration",
    location: { id: "landing", name: "Lantern landing", description: "A light flickers below the tide." },
    scene: { schema_version: "vtt.scene.v1", scene_id: "landing", name: "Lantern landing", grid_type: "square", cell_size_ft: 5, columns: 8, rows: 6, origin_ft: { x_ft: 0, y_ft: 0, z_ft: 0 } },
    party: [hero], combat: null as EncounterProjection | null,
    choices: [{ id: "enter", label: "Enter the keeper’s hall", description: "Follow the lantern light." }],
    journal: [{ id: "beacon", title: "The fading beacon", text: "Reach the beacon before nightfall." }],
    inventory: [{ id: "potion", name: "Healing draught", quantity: 1, description: "Restores health." }],
    objective: "Find Keeper Orin", dialogue: { speaker: "Mara", text: "We should hurry." },
    ending: null as { title: string; text: string } | null,
  };
}
export function receipt(commandId: string, revision = 1) {
  return { schema_version: "vtt.commit_response.v1", response_type: "commit", command_id: commandId,
    session_id: "lantern-test", revision, replayed: false, versions: adventureFixture().versions,
    first_sequence: null, last_sequence: null, events: [] };
}
