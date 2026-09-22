import assert from "node:assert/strict";
import test from "node:test";

import {
  activateGridlessMeasurementPoint,
  boardCellDistanceFeet,
  boardCellToFeet,
  boardCellToPixel,
  enumerateBoardCells,
  feetToBoardCell,
  feetToBoardPixel,
  moveGridlessCursor,
  parseBoardCalibration,
  pixelToBoardFeet,
  pixelDistanceFeet,
  pixelToBoardCell,
  type AxialHexCell,
  type BoardCalibration,
  type SquareBoardCell,
} from "../app/vtt-board-calibration";

test("moves a gridless keyboard cursor by unsnapped view pixels within map bounds", () => {
  let cursor = { x_px: 10.25, y_px: 20.75 };
  cursor = moveGridlessCursor(cursor, "ArrowRight", 100, 80);
  cursor = moveGridlessCursor(cursor, "ArrowUp", 100, 80, 10);
  assert.deepEqual(cursor, { x_px: 11.25, y_px: 10.75 });
  assert.deepEqual(
    moveGridlessCursor({ x_px: 0.25, y_px: 79.5 }, "ArrowDown", 100, 80),
    { x_px: 0.25, y_px: 80 },
  );
});

test("completes gridless measurement and ping coordinates with keyboard-only points", () => {
  const board = calibration("gridless");
  const origin: [number, number, number] = [2.5, 2.5, 0];
  let cursor = { x_px: 410.25, y_px: 305.75 };
  let measurement = activateGridlessMeasurementPoint(null, "gridless", cursor);
  cursor = moveGridlessCursor(cursor, "ArrowRight", 900, 700, 7.5);
  cursor = moveGridlessCursor(cursor, "ArrowDown", 900, 700, 2.25);
  measurement = activateGridlessMeasurementPoint(measurement, "gridless", cursor);
  assert.equal(
    pixelDistanceFeet(board, measurement.start, measurement.end!),
    Math.hypot(7.5, 2.25) / 72 * 5,
  );
  assert.deepEqual(pixelToBoardFeet(board, cursor, origin), [
    2.5 + 7.5 / 72 * 5,
    2.5 + 2.25 / 72 * 5,
    0,
  ]);
  assert.notEqual(cursor.x_px % board.cell_extent_px, 0);
});

function calibration(
  topology: BoardCalibration["topology"],
): BoardCalibration {
  return parseBoardCalibration({
    schema_version: "vtt.board_calibration.v1",
    topology,
    origin_x_px: 410.25,
    origin_y_px: 305.75,
    cell_extent_px: 72,
    distance_ft: 5,
  });
}

test("round-trips square and both hex orientations at calibrated centers", () => {
  for (const topology of ["square", "hex_flat", "hex_pointy"] as const) {
    const board = calibration(topology);
    const cells = topology === "square"
      ? [{ column: 0, row: 0 }, { column: 3, row: -2 }]
      : [{ q: 0, r: 0 }, { q: 3, r: -2 }];
    for (const cell of cells) {
      assert.deepEqual(pixelToBoardCell(board, boardCellToPixel(board, cell)), cell);
      assert.deepEqual(
        feetToBoardCell(board, boardCellToFeet(board, cell, [-10, 15, 2]), [-10, 15, 2]),
        cell,
      );
    }
  }
});

test("matches the deterministic cube tie and distance fixtures", () => {
  const board = parseBoardCalibration({
    schema_version: "vtt.board_calibration.v1",
    topology: "hex_pointy",
    origin_x_px: 0,
    origin_y_px: 0,
    cell_extent_px: 60,
    distance_ft: 5,
  });
  assert.deepEqual(pixelToBoardCell(board, { x_px: 30, y_px: 0 }), { q: 1, r: 0 });
  assert.equal(
    boardCellDistanceFeet(
      board,
      { q: -2, r: 3 } satisfies AxialHexCell,
      { q: 4, r: -1 } satisfies AxialHexCell,
    ),
    30,
  );
  assert.equal(
    boardCellDistanceFeet(
      calibration("square"),
      { column: -2, row: 3 } satisfies SquareBoardCell,
      { column: 4, row: -1 } satisfies SquareBoardCell,
    ),
    30,
  );
});

test("enumerates only complete calibrated cells and never invents gridless cells", () => {
  const square = parseBoardCalibration({
    schema_version: "vtt.board_calibration.v1",
    topology: "square",
    origin_x_px: 25,
    origin_y_px: 25,
    cell_extent_px: 50,
    distance_ft: 5,
  });
  assert.equal(enumerateBoardCells(square, 200, 150).length, 12);

  const flat = { ...square, topology: "hex_flat" as const };
  assert.ok(enumerateBoardCells(flat, 200, 150).length > 0);
  assert.deepEqual(enumerateBoardCells({ ...square, topology: "gridless" }, 200, 150), []);
});

test("round-trips gridless pixels through engine feet and measures the calibrated scale", () => {
  const board = parseBoardCalibration({
    schema_version: "vtt.board_calibration.v1",
    topology: "gridless",
    origin_x_px: 20,
    origin_y_px: 30,
    cell_extent_px: 40,
    distance_ft: 5,
  });
  const point = { x_px: 44, y_px: 62 };
  const feet = pixelToBoardFeet(board, point, [-10, 15, 2]);
  assert.deepEqual(feetToBoardPixel(board, feet, [-10, 15, 2]), point);
  assert.equal(pixelDistanceFeet(board, { x_px: 20, y_px: 30 }, point), 5);
});

test("strictly rejects malformed or unbounded calibration payloads", () => {
  const valid = calibration("square");
  assert.throws(() => parseBoardCalibration({ ...valid, grid_color: "#fff" }), /unexpected/i);
  assert.throws(() => parseBoardCalibration({ ...valid, cell_extent_px: 0 }), /extent/i);
  assert.throws(() => parseBoardCalibration({ ...valid, origin_x_px: Number.NaN }), /origin/i);
  assert.throws(() => parseBoardCalibration({ ...valid, topology: "isometric" }), /topology/i);
});
