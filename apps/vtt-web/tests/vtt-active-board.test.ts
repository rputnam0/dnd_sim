import assert from "node:assert/strict";
import test from "node:test";

import { selectActiveBoardPresentation } from "../app/vtt-active-board";
import type { VttSessionView } from "../app/vtt-client";

test("loading and error hydration expose no plausible board interaction", () => {
  for (const [error, status] of [[null, "loading"], ["invalid", "error"]] as const) {
    assert.deepEqual(selectActiveBoardPresentation(null, error), {
      status,
      board: null,
      cellsEnabled: false,
      tokensEnabled: false,
      movementEnabled: false,
    });
  }
});

test("a hydrated pointy board is the only enabled presentation", () => {
  const board = {
    schema_version: "vtt.active_board_projection.v1",
    scene_revision: 4,
    scene: {
      schema_version: "vtt.scene.v1",
      scene_id: "hex-room",
      name: "Hex Room",
      grid_type: "square",
      cell_size_ft: 5,
      columns: 8,
      rows: 6,
      origin_ft: { x_ft: 0, y_ft: 0, z_ft: 0 },
    },
    map_metadata: {
      schema_version: "vtt.scene_map_metadata.v1",
      name: "Hex Room",
      width_px: 800,
      height_px: 600,
      grid_size_px: 100,
      gridless: false,
      calibration: {
        schema_version: "vtt.board_calibration.v1",
        topology: "hex_pointy",
        origin_x_px: 100,
        origin_y_px: 100,
        cell_extent_px: 100,
        distance_ft: 5,
      },
    },
  } as const;
  const view = { active_board: board } as VttSessionView;
  const presentation = selectActiveBoardPresentation(view, null);
  assert.equal(presentation.status, "ready");
  assert.equal(presentation.board?.map_metadata.calibration.topology, "hex_pointy");
  assert.equal(presentation.cellsEnabled, true);
  assert.equal(presentation.tokensEnabled, true);
  assert.equal(presentation.movementEnabled, true);

  assert.deepEqual(
    selectActiveBoardPresentation(view, null, {
      schema_version: "vtt.scene_library_view.v1",
      table_id: "table-a",
      revision: 5,
      active_scene_id: "next-scene",
      scenes: [],
    }),
    {
      status: "loading",
      board: null,
      cellsEnabled: false,
      tokensEnabled: false,
      movementEnabled: false,
    },
  );
});
