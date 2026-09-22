import type { ActiveBoardProjection, VttSessionView } from "./vtt-client";
import type { SceneLibraryView } from "./vtt-scenes";

export type ActiveBoardPresentation =
  | {
      status: "ready";
      board: ActiveBoardProjection;
      cellsEnabled: true;
      tokensEnabled: true;
      movementEnabled: true;
    }
  | {
      status: "loading" | "error";
      board: null;
      cellsEnabled: false;
      tokensEnabled: false;
      movementEnabled: false;
    };

export function selectActiveBoardPresentation(
  view: VttSessionView | null,
  loadError: string | null,
  library: SceneLibraryView | null = null,
): ActiveBoardPresentation {
  const board = view?.active_board;
  const libraryMatches =
    library === null ||
    (board !== null &&
      board !== undefined &&
      library.active_scene_id === board.scene.scene_id &&
      library.revision === board.scene_revision);
  if (board !== null && board !== undefined && libraryMatches) {
    return {
      status: "ready",
      board,
      cellsEnabled: true,
      tokensEnabled: true,
      movementEnabled: true,
    };
  }
  return {
    status: loadError === null ? "loading" : "error",
    board: null,
    cellsEnabled: false,
    tokensEnabled: false,
    movementEnabled: false,
  };
}
