export type BoardTopology = "gridless" | "square" | "hex_flat" | "hex_pointy";

export interface BoardCalibration {
  schema_version: "vtt.board_calibration.v1";
  topology: BoardTopology;
  origin_x_px: number;
  origin_y_px: number;
  cell_extent_px: number;
  distance_ft: number;
}

export interface BoardPoint {
  x_px: number;
  y_px: number;
}

export interface GridlessMeasurementState {
  calibrationKey: string;
  start: BoardPoint;
  end: BoardPoint | null;
}

export interface SquareBoardCell {
  column: number;
  row: number;
}

export interface AxialHexCell {
  q: number;
  r: number;
}

export type BoardCell = SquareBoardCell | AxialHexCell;
export type FeetPoint = readonly [number, number, number];

const MAX_EXTENT_PX = 100_000;
const MAX_DISTANCE_FT = 100_000;
const MAX_RENDERED_CELLS = 10_000;

function objectValue(value: unknown, path: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`${path} must be an object`);
  }
  return value as Record<string, unknown>;
}

function finite(value: unknown, path: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new Error(`${path} must be finite`);
  }
  return value;
}

function positive(value: unknown, path: string, maximum: number): number {
  const result = finite(value, path);
  if (result <= 0 || result > maximum) {
    throw new Error(`${path} must be positive and bounded`);
  }
  return result;
}

export function parseBoardCalibration(
  value: unknown,
  path = "board_calibration",
): BoardCalibration {
  const data = objectValue(value, path);
  const keys = [
    "schema_version",
    "topology",
    "origin_x_px",
    "origin_y_px",
    "cell_extent_px",
    "distance_ft",
  ];
  if (
    Object.keys(data).length !== keys.length ||
    keys.some((key) => !(key in data))
  ) {
    throw new Error(`${path} contains unexpected or missing fields`);
  }
  if (data.schema_version !== "vtt.board_calibration.v1") {
    throw new Error(`${path}.schema_version is unsupported`);
  }
  if (
    data.topology !== "gridless" &&
    data.topology !== "square" &&
    data.topology !== "hex_flat" &&
    data.topology !== "hex_pointy"
  ) {
    throw new Error(`${path}.topology is unsupported`);
  }
  return {
    schema_version: "vtt.board_calibration.v1",
    topology: data.topology,
    origin_x_px: finite(data.origin_x_px, `${path}.origin_x_px`),
    origin_y_px: finite(data.origin_y_px, `${path}.origin_y_px`),
    cell_extent_px: positive(data.cell_extent_px, `${path}.cell_extent_px`, MAX_EXTENT_PX),
    distance_ft: positive(data.distance_ft, `${path}.distance_ft`, MAX_DISTANCE_FT),
  };
}

export function legacyBoardCalibration(
  gridSizePx: number,
  gridless: boolean,
): BoardCalibration {
  const extent = positive(gridSizePx, "grid_size_px", MAX_EXTENT_PX);
  return {
    schema_version: "vtt.board_calibration.v1",
    topology: gridless ? "gridless" : "square",
    origin_x_px: extent / 2,
    origin_y_px: extent / 2,
    cell_extent_px: extent,
    distance_ft: 5,
  };
}

function requireCell(calibration: BoardCalibration, cell: BoardCell): void {
  if (calibration.topology === "gridless") {
    throw new Error("gridless calibration does not expose cells");
  }
  if (calibration.topology === "square" && !("column" in cell)) {
    throw new Error("square calibration requires a square cell");
  }
  if (calibration.topology.startsWith("hex_") && !("q" in cell)) {
    throw new Error("hex calibration requires an axial cell");
  }
}

export function boardCellToPixel(
  calibration: BoardCalibration,
  cell: BoardCell,
): BoardPoint {
  requireCell(calibration, cell);
  if ("column" in cell) {
    return {
      x_px: calibration.origin_x_px + cell.column * calibration.cell_extent_px,
      y_px: calibration.origin_y_px + cell.row * calibration.cell_extent_px,
    };
  }
  if (calibration.topology === "hex_pointy") {
    return {
      x_px: calibration.origin_x_px + calibration.cell_extent_px * (cell.q + cell.r / 2),
      y_px: calibration.origin_y_px + calibration.cell_extent_px * Math.sqrt(3) / 2 * cell.r,
    };
  }
  return {
    x_px: calibration.origin_x_px + calibration.cell_extent_px * Math.sqrt(3) / 2 * cell.q,
    y_px: calibration.origin_y_px + calibration.cell_extent_px * (cell.r + cell.q / 2),
  };
}

function roundHalfAwayFromZero(value: number): number {
  return value >= 0 ? Math.floor(value + 0.5) : Math.ceil(value - 0.5);
}

function roundAxial(qFraction: number, rFraction: number): AxialHexCell {
  const sFraction = -qFraction - rFraction;
  let q = roundHalfAwayFromZero(qFraction);
  let r = roundHalfAwayFromZero(rFraction);
  const s = roundHalfAwayFromZero(sFraction);
  const qError = Math.abs(q - qFraction);
  const rError = Math.abs(r - rFraction);
  const sError = Math.abs(s - sFraction);
  if (qError >= rError && qError >= sError) q = -r - s;
  else if (rError >= sError) r = -q - s;
  return { q: Object.is(q, -0) ? 0 : q, r: Object.is(r, -0) ? 0 : r };
}

export function pixelToBoardCell(
  calibration: BoardCalibration,
  point: BoardPoint,
): BoardCell {
  if (calibration.topology === "gridless") {
    throw new Error("gridless calibration does not expose cells");
  }
  const x = (finite(point.x_px, "point.x_px") - calibration.origin_x_px) / calibration.cell_extent_px;
  const y = (finite(point.y_px, "point.y_px") - calibration.origin_y_px) / calibration.cell_extent_px;
  if (calibration.topology === "square") {
    return { column: Math.floor(x + 0.5), row: Math.floor(y + 0.5) };
  }
  if (calibration.topology === "hex_pointy") {
    const r = 2 / Math.sqrt(3) * y;
    return roundAxial(x - r / 2, r);
  }
  const q = 2 / Math.sqrt(3) * x;
  return roundAxial(q, y - q / 2);
}

export function boardCellToFeet(
  calibration: BoardCalibration,
  cell: BoardCell,
  originFeet: FeetPoint,
): [number, number, number] {
  const pixel = boardCellToPixel(calibration, cell);
  return [
    originFeet[0] + (pixel.x_px - calibration.origin_x_px) / calibration.cell_extent_px * calibration.distance_ft,
    originFeet[1] + (pixel.y_px - calibration.origin_y_px) / calibration.cell_extent_px * calibration.distance_ft,
    originFeet[2],
  ];
}

export function feetToBoardCell(
  calibration: BoardCalibration,
  point: FeetPoint,
  originFeet: FeetPoint,
): BoardCell {
  return pixelToBoardCell(calibration, {
    x_px: calibration.origin_x_px + (point[0] - originFeet[0]) / calibration.distance_ft * calibration.cell_extent_px,
    y_px: calibration.origin_y_px + (point[1] - originFeet[1]) / calibration.distance_ft * calibration.cell_extent_px,
  });
}

export function pixelToBoardFeet(
  calibration: BoardCalibration,
  point: BoardPoint,
  originFeet: FeetPoint,
): [number, number, number] {
  return [
    originFeet[0] + (finite(point.x_px, "point.x_px") - calibration.origin_x_px) / calibration.cell_extent_px * calibration.distance_ft,
    originFeet[1] + (finite(point.y_px, "point.y_px") - calibration.origin_y_px) / calibration.cell_extent_px * calibration.distance_ft,
    originFeet[2],
  ];
}

export function feetToBoardPixel(
  calibration: BoardCalibration,
  point: FeetPoint,
  originFeet: FeetPoint,
): BoardPoint {
  return {
    x_px: calibration.origin_x_px + (point[0] - originFeet[0]) / calibration.distance_ft * calibration.cell_extent_px,
    y_px: calibration.origin_y_px + (point[1] - originFeet[1]) / calibration.distance_ft * calibration.cell_extent_px,
  };
}

export function pixelDistanceFeet(
  calibration: BoardCalibration,
  start: BoardPoint,
  end: BoardPoint,
): number {
  return Math.hypot(end.x_px - start.x_px, end.y_px - start.y_px) /
    calibration.cell_extent_px * calibration.distance_ft;
}

export function moveGridlessCursor(
  point: BoardPoint,
  key: "ArrowLeft" | "ArrowRight" | "ArrowUp" | "ArrowDown",
  widthPx: number,
  heightPx: number,
  stepPx = 1,
): BoardPoint {
  if (
    !Number.isSafeInteger(widthPx) ||
    !Number.isSafeInteger(heightPx) ||
    widthPx < 1 ||
    heightPx < 1 ||
    !Number.isFinite(stepPx) ||
    stepPx <= 0
  ) {
    throw new Error("gridless keyboard bounds and step must be positive");
  }
  const deltaX = key === "ArrowLeft" ? -stepPx : key === "ArrowRight" ? stepPx : 0;
  const deltaY = key === "ArrowUp" ? -stepPx : key === "ArrowDown" ? stepPx : 0;
  return {
    x_px: Math.min(widthPx, Math.max(0, finite(point.x_px, "point.x_px") + deltaX)),
    y_px: Math.min(heightPx, Math.max(0, finite(point.y_px, "point.y_px") + deltaY)),
  };
}

export function activateGridlessMeasurementPoint(
  current: GridlessMeasurementState | null,
  calibrationKey: string,
  point: BoardPoint,
): GridlessMeasurementState {
  return current?.calibrationKey === calibrationKey && current.end === null
    ? { ...current, end: { ...point } }
    : { calibrationKey, start: { ...point }, end: null };
}

export function boardCellDistanceFeet(
  calibration: BoardCalibration,
  start: BoardCell,
  end: BoardCell,
): number {
  requireCell(calibration, start);
  requireCell(calibration, end);
  if ("column" in start && "column" in end) {
    return Math.max(Math.abs(end.column - start.column), Math.abs(end.row - start.row)) * calibration.distance_ft;
  }
  if ("q" in start && "q" in end) {
    const dq = end.q - start.q;
    const dr = end.r - start.r;
    return Math.max(Math.abs(dq), Math.abs(dr), Math.abs(dq + dr)) * calibration.distance_ft;
  }
  throw new Error("cell types must match calibration topology");
}

function cellIsInside(
  calibration: BoardCalibration,
  cell: BoardCell,
  widthPx: number,
  heightPx: number,
): boolean {
  const center = boardCellToPixel(calibration, cell);
  const halfWidth = calibration.topology === "hex_flat"
    ? calibration.cell_extent_px / Math.sqrt(3)
    : calibration.cell_extent_px / 2;
  const halfHeight = calibration.topology === "hex_pointy"
    ? calibration.cell_extent_px / Math.sqrt(3)
    : calibration.cell_extent_px / 2;
  return center.x_px - halfWidth >= 0 && center.y_px - halfHeight >= 0 &&
    center.x_px + halfWidth <= widthPx && center.y_px + halfHeight <= heightPx;
}

export function requireUsableBoardCalibration(
  calibration: BoardCalibration,
  widthPx: number,
  heightPx: number,
): BoardCalibration {
  if (!Number.isSafeInteger(widthPx) || !Number.isSafeInteger(heightPx) || widthPx < 1 || heightPx < 1) {
    throw new Error("map dimensions must be positive safe integers");
  }
  if (calibration.topology === "gridless") {
    if (
      calibration.origin_x_px < 0 || calibration.origin_x_px >= widthPx ||
      calibration.origin_y_px < 0 || calibration.origin_y_px >= heightPx
    ) {
      throw new Error("gridless calibration origin must lie inside the map");
    }
    return calibration;
  }
  const center = pixelToBoardCell(calibration, { x_px: widthPx / 2, y_px: heightPx / 2 });
  const candidates: BoardCell[] = [center];
  if ("column" in center) {
    for (let row = -2; row <= 2; row += 1) {
      for (let column = -2; column <= 2; column += 1) {
        candidates.push({ column: center.column + column, row: center.row + row });
      }
    }
  } else {
    const deltas = [[1, 0], [1, -1], [0, -1], [-1, 0], [-1, 1], [0, 1]] as const;
    for (const [dq, dr] of deltas) candidates.push({ q: center.q + dq, r: center.r + dr });
    for (const [dq, dr] of deltas) {
      for (const [dq2, dr2] of deltas) {
        candidates.push({ q: center.q + dq + dq2, r: center.r + dr + dr2 });
      }
    }
  }
  if (!candidates.some((cell) => cellIsInside(calibration, cell, widthPx, heightPx))) {
    throw new Error("calibration does not provide a complete usable cell");
  }
  return calibration;
}

function appendCell(cells: BoardCell[], cell: BoardCell): void {
  cells.push(cell);
  if (cells.length > MAX_RENDERED_CELLS) {
    throw new Error(`calibration exceeds the ${MAX_RENDERED_CELLS}-cell presentation budget`);
  }
}

export function enumerateBoardCells(
  calibration: BoardCalibration,
  widthPx: number,
  heightPx: number,
): BoardCell[] {
  if (!Number.isSafeInteger(widthPx) || !Number.isSafeInteger(heightPx) || widthPx < 1 || heightPx < 1) {
    throw new Error("map dimensions must be positive safe integers");
  }
  if (calibration.topology === "gridless") return [];
  const cells: BoardCell[] = [];
  const extent = calibration.cell_extent_px;
  if (calibration.topology === "square") {
    const half = extent / 2;
    const minColumn = Math.ceil((half - calibration.origin_x_px) / extent);
    const maxColumn = Math.floor((widthPx - half - calibration.origin_x_px) / extent);
    const minRow = Math.ceil((half - calibration.origin_y_px) / extent);
    const maxRow = Math.floor((heightPx - half - calibration.origin_y_px) / extent);
    for (let row = minRow; row <= maxRow; row += 1) {
      for (let column = minColumn; column <= maxColumn; column += 1) appendCell(cells, { column, row });
    }
    return cells;
  }
  const span = Math.ceil((widthPx + heightPx + Math.abs(calibration.origin_x_px) + Math.abs(calibration.origin_y_px)) / extent) + 4;
  if (span * span * 4 > MAX_RENDERED_CELLS * 50) {
    throw new Error("calibration search exceeds the presentation budget");
  }
  for (let r = -span; r <= span; r += 1) {
    for (let q = -span; q <= span; q += 1) {
      const cell = { q, r };
      if (cellIsInside(calibration, cell, widthPx, heightPx)) appendCell(cells, cell);
    }
  }
  return cells;
}
