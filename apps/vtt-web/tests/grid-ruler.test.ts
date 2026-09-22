import assert from "node:assert/strict";
import test from "node:test";

import {
  EMPTY_GRID_MEASUREMENT,
  gridMeasurementDistanceFeet,
  nextGridMeasurement,
} from "../app/grid-ruler";
import type { SquareGridScene } from "../app/vtt-client";

const scene: SquareGridScene = {
  schema_version: "vtt.scene.v1",
  scene_id: "echo-vault",
  name: "Echo Vault",
  grid_type: "square",
  cell_size_ft: 5,
  columns: 8,
  rows: 6,
  origin_ft: { x_ft: 0, y_ft: 0, z_ft: 0 },
};

test("selects a start, then an end, then begins a fresh measurement", () => {
  const withStart = nextGridMeasurement(EMPTY_GRID_MEASUREMENT, {
    column: 1,
    row: 2,
  });
  assert.deepEqual(withStart, {
    start: { column: 1, row: 2 },
    end: null,
  });

  const complete = nextGridMeasurement(withStart, { column: 7, row: 5 });
  assert.deepEqual(complete, {
    start: { column: 1, row: 2 },
    end: { column: 7, row: 5 },
  });
  assert.deepEqual(withStart, {
    start: { column: 1, row: 2 },
    end: null,
  });

  assert.deepEqual(nextGridMeasurement(complete, { column: 0, row: 0 }), {
    start: { column: 0, row: 0 },
    end: null,
  });
});

test("measures direct square-grid distance with the 5e diagonal rule", () => {
  assert.equal(
    gridMeasurementDistanceFeet(scene, {
      start: { column: 1, row: 1 },
      end: { column: 4, row: 3 },
    }),
    15,
  );
  assert.equal(
    gridMeasurementDistanceFeet(scene, {
      start: { column: 7, row: 5 },
      end: { column: 7, row: 5 },
    }),
    0,
  );
  assert.equal(
    gridMeasurementDistanceFeet(scene, {
      start: { column: 0, row: 0 },
      end: null,
    }),
    null,
  );
  assert.equal(
    gridMeasurementDistanceFeet(
      { ...scene, cell_size_ft: 10 },
      {
        start: { column: 1, row: 1 },
        end: { column: 4, row: 3 },
      },
    ),
    30,
  );
});

test("rejects measurement endpoints outside the presented scene", () => {
  assert.throws(
    () =>
      gridMeasurementDistanceFeet(scene, {
        start: { column: 0, row: 0 },
        end: { column: 8, row: 0 },
      }),
    /outside the scene bounds/i,
  );
});
