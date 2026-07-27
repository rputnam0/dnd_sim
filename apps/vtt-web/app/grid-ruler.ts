import type { GridCell, SquareGridScene } from "./vtt-client";

export interface GridMeasurement {
  start: GridCell | null;
  end: GridCell | null;
}

export const EMPTY_GRID_MEASUREMENT: GridMeasurement = {
  start: null,
  end: null,
};

function copyCell(cell: GridCell): GridCell {
  if (
    !Number.isInteger(cell.column) ||
    !Number.isInteger(cell.row) ||
    cell.column < 0 ||
    cell.row < 0
  ) {
    throw new Error("Grid measurement cell must use non-negative integers");
  }
  return { column: cell.column, row: cell.row };
}

function assertCellInScene(scene: SquareGridScene, cell: GridCell): void {
  if (cell.column >= scene.columns || cell.row >= scene.rows) {
    throw new Error("Grid measurement cell is outside the scene bounds");
  }
}

export function nextGridMeasurement(
  current: GridMeasurement,
  selectedCell: GridCell,
): GridMeasurement {
  const cell = copyCell(selectedCell);
  if (current.start === null || current.end !== null) {
    return { start: cell, end: null };
  }
  return {
    start: copyCell(current.start),
    end: cell,
  };
}

export function gridMeasurementDistanceFeet(
  scene: SquareGridScene,
  measurement: GridMeasurement,
): number | null {
  if (measurement.start === null || measurement.end === null) return null;

  const start = copyCell(measurement.start);
  const end = copyCell(measurement.end);
  assertCellInScene(scene, start);
  assertCellInScene(scene, end);
  const columnDistance = Math.abs(end.column - start.column);
  const rowDistance = Math.abs(end.row - start.row);
  return Math.max(columnDistance, rowDistance) * scene.cell_size_ft;
}
