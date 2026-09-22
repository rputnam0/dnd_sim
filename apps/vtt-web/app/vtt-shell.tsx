"use client";

import {
  useEffect,
  useState,
  type KeyboardEvent,
  type ReactNode,
} from "react";

import type { VttTableRole } from "./vtt-access";
import {
  assertWorkspacePanelRegistry,
  decodeWorkspacePreferences,
  encodeWorkspacePreferences,
  panelsForRole,
  panelsForWorkspace,
  resolveWorkspacePreferences,
  type VttWorkspaceMode,
  type VttWorkspacePanelAccess,
  type VttWorkspacePreferenceStorage,
  type VttWorkspacePreferences,
} from "./vtt-workspace-state";

export interface VttShellPanel extends VttWorkspacePanelAccess {
  label: string;
  content: ReactNode;
}

interface VttShellProps {
  role: VttTableRole;
  worldName: string;
  sceneName?: string | null;
  connectionLabel: string;
  mapSlot: ReactNode;
  actionSlot: ReactNode;
  initiativeSlot?: ReactNode;
  panels: readonly VttShellPanel[];
  preferenceStorage?: VttWorkspacePreferenceStorage;
  productName?: string;
}

function readInitialPreferences(
  storage: VttWorkspacePreferenceStorage | undefined,
  role: VttTableRole,
  panels: readonly VttShellPanel[],
): VttWorkspacePreferences {
  let candidate: VttWorkspacePreferences | null = null;
  try {
    candidate = decodeWorkspacePreferences(storage?.read() ?? null);
  } catch {
    candidate = null;
  }
  return resolveWorkspacePreferences({ candidate, role, panels });
}

function modeLabel(mode: VttWorkspaceMode): string {
  return mode === "play" ? "Play" : "Prepare";
}

export function VttShell({
  role,
  worldName,
  sceneName = null,
  connectionLabel,
  mapSlot,
  actionSlot,
  initiativeSlot,
  panels,
  preferenceStorage,
  productName = "DND Sim VTT",
}: VttShellProps) {
  assertWorkspacePanelRegistry(panels);
  for (const panel of panels) {
    if (panel.label.length === 0 || panel.label.trim() !== panel.label) {
      throw new Error(
        `Workspace panel "${panel.id}" must have a canonical non-empty label`,
      );
    }
  }
  const [candidate, setCandidate] = useState<VttWorkspacePreferences>(() =>
    readInitialPreferences(preferenceStorage, role, panels),
  );
  const workspace = resolveWorkspacePreferences({ candidate, role, panels });
  const visiblePanels = panelsForWorkspace(panels, role, workspace.mode);
  const authorizedPanels = panelsForRole(panels, role);
  const activePanel = visiblePanels.find(
    (panel) => panel.id === workspace.panelId,
  );

  useEffect(() => {
    if (preferenceStorage === undefined || activePanel === undefined) return;
    try {
      preferenceStorage.write(
        encodeWorkspacePreferences(
          { mode: workspace.mode, panelId: activePanel.id },
          { role, panels },
        ),
      );
    } catch {
      // Local presentation preferences must never make the authoritative table unusable.
    }
  }, [activePanel, panels, preferenceStorage, role, workspace.mode]);

  const selectMode = (mode: VttWorkspaceMode) => {
    setCandidate(
      resolveWorkspacePreferences({
        candidate: { mode, panelId: workspace.panelId },
        role,
        panels,
      }),
    );
  };
  const selectPanelByKeyboard = (
    event: KeyboardEvent<HTMLButtonElement>,
    panelIndex: number,
  ) => {
    let nextIndex: number | null = null;
    if (event.key === "ArrowRight") {
      nextIndex = (panelIndex + 1) % visiblePanels.length;
    } else if (event.key === "ArrowLeft") {
      nextIndex = (panelIndex - 1 + visiblePanels.length) % visiblePanels.length;
    } else if (event.key === "Home") {
      nextIndex = 0;
    } else if (event.key === "End") {
      nextIndex = visiblePanels.length - 1;
    }
    if (nextIndex === null || visiblePanels.length === 0) return;
    event.preventDefault();
    const nextPanel = visiblePanels[nextIndex];
    setCandidate({ mode: workspace.mode, panelId: nextPanel.id });
    event.currentTarget.parentElement
      ?.querySelector<HTMLButtonElement>(`#vtt-panel-tab-${nextPanel.id}`)
      ?.focus();
  };

  return (
    <div className="vtt-shell" data-role={role} data-workspace-mode={workspace.mode}>
      <nav className="vtt-shell-skip-links" aria-label="Skip to tabletop area">
        <a href="#vtt-map">Skip to map</a>
        <a href="#vtt-actions">Skip to actions</a>
        <a
          href={
            activePanel === undefined
              ? "#vtt-workspace-panel"
              : `#vtt-workspace-panel-${activePanel.id}`
          }
        >
          Skip to workspace panel
        </a>
      </nav>

      <header className="vtt-shell-app-bar" aria-label="Virtual tabletop status">
        <div className="vtt-shell-identity">
          <p className="vtt-shell-product-name">{productName}</p>
          <h1>{worldName}</h1>
          {sceneName ? <p className="vtt-shell-scene-name">{sceneName}</p> : null}
        </div>
        <p className="vtt-shell-connection" role="status" aria-live="polite">
          {connectionLabel}
        </p>
        <nav className="vtt-shell-modes" aria-label="Workspace mode">
          <button
            type="button"
            aria-pressed={workspace.mode === "play"}
            onClick={() => selectMode("play")}
          >
            Play
          </button>
          {role === "gm" ? (
            <button
              type="button"
              aria-pressed={workspace.mode === "prepare"}
              onClick={() => selectMode("prepare")}
            >
              Prepare
            </button>
          ) : null}
        </nav>
      </header>

      <main className="vtt-shell-main">
        <div className="vtt-shell-stage">
          <section
            className="vtt-shell-map-slot"
            id="vtt-map"
            aria-label="Tactical map"
            tabIndex={-1}
          >
            {mapSlot}
          </section>
          <section
            className="vtt-shell-action-slot"
            id="vtt-actions"
            aria-label="Table actions"
            tabIndex={-1}
          >
            {actionSlot}
          </section>
        </div>

        {initiativeSlot !== undefined ? (
          <aside
            className="vtt-shell-initiative-slot"
            id="vtt-initiative"
            aria-label="Initiative order"
          >
            {initiativeSlot}
          </aside>
        ) : null}

        <aside className="vtt-shell-panel-dock" aria-label="Workspace tools">
          <p
            className="vtt-shell-workspace-announcement"
            aria-live="polite"
          >
            {modeLabel(workspace.mode)} workspace · {activePanel?.label ?? "No"} panel
          </p>
          <div
            className="vtt-shell-panel-tabs"
            role="tablist"
            aria-label={`${modeLabel(workspace.mode)} workspace panels`}
          >
            {visiblePanels.map((panel, panelIndex) => (
              <button
                type="button"
                role="tab"
                id={`vtt-panel-tab-${panel.id}`}
                aria-controls={`vtt-workspace-panel-${panel.id}`}
                aria-selected={panel.id === activePanel?.id}
                tabIndex={panel.id === activePanel?.id ? 0 : -1}
                key={panel.id}
                onClick={() =>
                  setCandidate({ mode: workspace.mode, panelId: panel.id })
                }
                onKeyDown={(event) =>
                  selectPanelByKeyboard(event, panelIndex)
                }
              >
                {panel.label}
              </button>
            ))}
          </div>
          <div
            className="vtt-shell-panel-stack"
            id="vtt-workspace-panel"
            tabIndex={-1}
          >
            {authorizedPanels.map((panel) => {
              const isActive = panel.id === activePanel?.id;
              const hasVisibleTab = visiblePanels.some(
                (visiblePanel) => visiblePanel.id === panel.id,
              );
              return (
                <section
                  className="vtt-shell-active-panel"
                  id={`vtt-workspace-panel-${panel.id}`}
                  role="tabpanel"
                  aria-label={hasVisibleTab ? undefined : panel.label}
                  aria-labelledby={
                    hasVisibleTab ? `vtt-panel-tab-${panel.id}` : undefined
                  }
                  data-panel-id={panel.id}
                  data-active={isActive ? "true" : "false"}
                  tabIndex={-1}
                  hidden={!isActive}
                  key={panel.id}
                >
                  <h2 className="vtt-shell-panel-title">{panel.label}</h2>
                  {panel.content}
                </section>
              );
            })}
            {activePanel === undefined ? (
              <p role="status">No workspace panels are available for this role.</p>
            ) : null}
          </div>
        </aside>
      </main>
    </div>
  );
}
