import type { VttTableRole } from "./vtt-access";

export type VttWorkspaceMode = "play" | "prepare";

export interface VttWorkspacePanelAccess {
  id: string;
  modes: readonly VttWorkspaceMode[];
  roles?: readonly VttTableRole[];
}

export interface VttWorkspacePreferences {
  mode: VttWorkspaceMode;
  panelId: string | null;
}

export interface VttWorkspacePreferenceStorage {
  read: () => string | null;
  write: (value: string) => void;
}

interface WorkspaceAccessContext {
  role: VttTableRole;
  panels: readonly VttWorkspacePanelAccess[];
}

interface ResolveWorkspacePreferencesInput extends WorkspaceAccessContext {
  candidate: VttWorkspacePreferences | null;
}

export const VTT_PLAY_PANEL_IDS = [
  "combat",
  "activity",
  "chat",
  "journal",
  "participants",
  "events",
] as const;

export const VTT_PREPARE_PANEL_IDS = [
  "scenes",
  "tokens",
  "visibility",
  "journal",
  "sound",
] as const;

const PANEL_ID_PATTERN = /^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$/;
const TABLE_ROLES = new Set<VttTableRole>(["gm", "player", "spectator"]);
const WORKSPACE_MODES = new Set<VttWorkspaceMode>(["play", "prepare"]);

function isPanelId(value: unknown): value is string {
  return (
    typeof value === "string" &&
    value.length <= 64 &&
    PANEL_ID_PATTERN.test(value)
  );
}

export function assertWorkspacePanelRegistry(
  panels: readonly VttWorkspacePanelAccess[],
): void {
  const panelIds = new Set<string>();
  for (const [index, panel] of panels.entries()) {
    if (!isPanelId(panel.id)) {
      throw new Error(
        `workspace panel ${index} must have a canonical lowercase panel ID`,
      );
    }
    if (panelIds.has(panel.id)) {
      throw new Error(`workspace panel ID "${panel.id}" must be unique`);
    }
    panelIds.add(panel.id);
    if (
      panel.modes.length === 0 ||
      new Set(panel.modes).size !== panel.modes.length ||
      panel.modes.some((mode) => !WORKSPACE_MODES.has(mode))
    ) {
      throw new Error(
        `workspace panel "${panel.id}" must declare unique Play or Prepare modes`,
      );
    }
    if (
      panel.roles !== undefined &&
      (panel.roles.length === 0 ||
        new Set(panel.roles).size !== panel.roles.length ||
        panel.roles.some((role) => !TABLE_ROLES.has(role)))
    ) {
      throw new Error(
        `workspace panel "${panel.id}" must declare unique table roles`,
      );
    }
  }
}

export function panelsForWorkspace<T extends VttWorkspacePanelAccess>(
  panels: readonly T[],
  role: VttTableRole,
  mode: VttWorkspaceMode,
): T[] {
  assertWorkspacePanelRegistry(panels);
  if (mode === "prepare" && role !== "gm") return [];
  return panels.filter(
    (panel) =>
      panel.modes.includes(mode) &&
      (panel.roles === undefined || panel.roles.includes(role)),
  );
}

export function panelsForRole<T extends VttWorkspacePanelAccess>(
  panels: readonly T[],
  role: VttTableRole,
): T[] {
  assertWorkspacePanelRegistry(panels);
  return panels.filter(
    (panel) =>
      (panel.roles === undefined || panel.roles.includes(role)) &&
      (role === "gm" || panel.modes.includes("play")),
  );
}

export function decodeWorkspacePreferences(
  serialized: string | null,
): VttWorkspacePreferences | null {
  if (serialized === null || serialized.length === 0 || serialized.length > 256) {
    return null;
  }
  try {
    const value: unknown = JSON.parse(serialized);
    if (typeof value !== "object" || value === null || Array.isArray(value)) {
      return null;
    }
    const record = value as Record<string, unknown>;
    const keys = Object.keys(record);
    if (
      keys.length !== 2 ||
      !keys.includes("mode") ||
      !keys.includes("panel_id") ||
      !WORKSPACE_MODES.has(record.mode as VttWorkspaceMode) ||
      !isPanelId(record.panel_id)
    ) {
      return null;
    }
    return {
      mode: record.mode as VttWorkspaceMode,
      panelId: record.panel_id,
    };
  } catch {
    return null;
  }
}

export function resolveWorkspacePreferences({
  candidate,
  role,
  panels,
}: ResolveWorkspacePreferencesInput): VttWorkspacePreferences {
  assertWorkspacePanelRegistry(panels);
  const requestedMode = role === "gm" ? candidate?.mode : "play";
  const playPanels = panelsForWorkspace(panels, role, "play");
  const preparePanels = panelsForWorkspace(panels, role, "prepare");
  let mode: VttWorkspaceMode;
  if (requestedMode === "prepare" && preparePanels.length > 0) {
    mode = "prepare";
  } else if (playPanels.length > 0) {
    mode = "play";
  } else if (role === "gm" && preparePanels.length > 0) {
    mode = "prepare";
  } else {
    mode = "play";
  }
  const availablePanels = mode === "prepare" ? preparePanels : playPanels;
  const requestedPanel = availablePanels.find(
    (panel) => panel.id === candidate?.panelId,
  );
  return {
    mode,
    panelId: requestedPanel?.id ?? availablePanels[0]?.id ?? null,
  };
}

export function encodeWorkspacePreferences(
  preferences: VttWorkspacePreferences,
  context: WorkspaceAccessContext,
): string {
  if (preferences.panelId === null) {
    throw new Error("Workspace preferences require an available panel ID");
  }
  const panels = panelsForWorkspace(
    context.panels,
    context.role,
    preferences.mode,
  );
  if (!panels.some((panel) => panel.id === preferences.panelId)) {
    throw new Error(
      `Workspace panel "${preferences.panelId}" is not an available panel`,
    );
  }
  return JSON.stringify({
    mode: preferences.mode,
    panel_id: preferences.panelId,
  });
}
