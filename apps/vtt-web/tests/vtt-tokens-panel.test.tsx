import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import TestRenderer, { act } from "react-test-renderer";

import { VttTokensPanel } from "../app/vtt-tokens-panel";
import type { VttTokensController } from "../app/use-vtt-tokens";

const reactTestEnvironment: typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean } = globalThis;
reactTestEnvironment.IS_REACT_ACT_ENVIRONMENT = true;

test("token workshop fails closed while its first projection hydrates", async () => {
  const controller = {
    view: null,
    status: "loading",
    operation: null,
    error: null,
    canMutate: false,
    createToken: async () => undefined,
    updateToken: async () => undefined,
    duplicateToken: async () => undefined,
    deleteToken: async () => undefined,
    retry: () => undefined,
  } as unknown as VttTokensController;
  let renderer: TestRenderer.ReactTestRenderer;
  await act(async () => {
    renderer = TestRenderer.create(
      createElement(VttTokensPanel, {
        table: {
          schema_version: "vtt.table_view.v1",
          access_mode: "open_local",
          table_id: "table-a",
          current_participant: {
            schema_version: "vtt.participant.v1",
            participant_id: "local",
            display_name: "Local GM",
            role: "gm",
            owned_actor_ids: [],
          },
          participants: [],
        },
        scene: {
          schema_version: "vtt.scene.v1",
          scene_id: "scene-a",
          name: "Loading board",
          grid_type: "square",
          cell_size_ft: 5,
          columns: 2,
          rows: 2,
          origin_ft: { x_ft: 0, y_ft: 0, z_ft: 0 },
        },
        mapMetadata: {
          schema_version: "vtt.scene_map_metadata.v1",
          name: "Loading board",
          width_px: 100,
          height_px: 100,
          grid_size_px: 50,
          gridless: false,
          calibration: {
            schema_version: "vtt.board_calibration.v1",
            topology: "square",
            origin_x_px: 25,
            origin_y_px: 25,
            cell_extent_px: 50,
            distance_ft: 5,
          },
        },
        actors: {},
        tokens: controller,
      }),
    );
  });
  assert.match(JSON.stringify(renderer!.toJSON()), /Loading tokens/);
  assert.match(JSON.stringify(renderer!.toJSON()), /No tokens are visible/);
  await act(async () => renderer!.unmount());
});
