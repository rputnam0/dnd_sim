import type { TurnActionChoice, TurnChoices } from "./vtt-client";

export interface TurnSelection {
  actionName: string;
  targetId: string | null;
}

/** Select the first server-authored action and its first structural candidate. */
export function initialTurnSelection(choices: TurnChoices | null): TurnSelection {
  const action =
    choices?.actions.find(
      (candidate) =>
        !candidate.requires_explicit_targets ||
        candidate.selectable_target_ids.length > 0,
    ) ?? choices?.actions[0];
  return {
    actionName: action?.action_name ?? "",
    targetId:
      action?.requires_explicit_targets === true
        ? action.selectable_target_ids[0] ?? null
        : null,
  };
}

/** Build explicit targets without accepting an ID absent from the server choice. */
export function selectedTargetIdsForChoice(
  choice: TurnActionChoice | undefined,
  selectedTargetId: string | null,
): string[] {
  if (!choice?.requires_explicit_targets || selectedTargetId === null) {
    return [];
  }
  return choice.selectable_target_ids.includes(selectedTargetId)
    ? [selectedTargetId]
    : [];
}
