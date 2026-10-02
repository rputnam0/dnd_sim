"use client";

import { TacticalMap } from "./echo-vault-table";
import { legacyBoardCalibration } from "./vtt-board-calibration";
import type { AdventureView } from "./adventure-client";
import type { EncounterProjection, GridCell, GridMovementPlan } from "./vtt-client";
import type { TokenRecord } from "./vtt-tokens";

const noop = () => undefined;
const emptyMeasurement = { start: null, end: null };

export default function AdventureMap({ view, selectedActorId, targets, targetId, reachable, movement, onActor, onTarget, onCell }: {
  view: AdventureView; selectedActorId: string; targets: Set<string>; targetId: string | null;
  reachable: Set<string>; movement: GridMovementPlan | null;
  onActor: (id: string) => void; onTarget: (id: string) => void; onCell: (cell: GridCell) => void;
}) {
  const projection: EncounterProjection = view.combat ?? {
    phase: "unstarted", outcome: null, winner: null, current_index: 0, active_actor_id: null,
    round_number: 1, max_rounds: 1, initiative_order: view.party.map((actor) => actor.actor_id),
    actors: Object.fromEntries(view.party.map((actor) => [actor.actor_id, actor])),
    prompt: null, result: null, choices: null,
  };
  const tokens: TokenRecord[] = Object.values(projection.actors).map((actor) => ({
    schema_version: "vtt.token_record.v1", token_id: actor.actor_id, scene_id: view.scene.scene_id,
    actor_id: actor.actor_id, name: actor.name,
    pose: { schema_version: "vtt.token_pose.v1",
      position_ft: { x_ft: actor.position[0], y_ft: actor.position[1], z_ft: actor.position[2] },
      width_ft: view.scene.cell_size_ft, height_ft: view.scene.cell_size_ft, rotation_degrees: 0, layer: 0 },
    visibility: "public", locked: false, nameplate: "always", show_hp_bar: true,
    aura_radius_ft: 0, aura_color: "#67d1ad", condition_labels: actor.conditions,
  }));
  return <TacticalMap
    playerMode
    scene={view.scene}
    mapMetadata={{ schema_version: "vtt.scene_map_metadata.v1", name: view.location.name,
      width_px: view.scene.columns * 80, height_px: view.scene.rows * 80, grid_size_px: 80,
      gridless: false, calibration: { ...legacyBoardCalibration(80, false), distance_ft: view.scene.cell_size_ft } }}
    mapUrl={`/assets/adventure/${encodeURIComponent(view.location.id)}.svg`}
    mapLoadError={null} projection={projection} tokens={tokens} tokenStatus="live" tokenError={null}
    visibilityProjection={null} visibilitySources={{ sceneId: null, sceneRevision: null,
      tokenRevision: null, visibilityRevision: null, encounterRevision: null }}
    visibilityStatus="live" visibilityError={null} showVisibilityMask={false}
    selectedActorId={selectedActorId} selectableTargetIds={targets} selectedTargetId={targetId}
    reachableCells={reachable} movementPlan={movement} measureMode={false} measurement={emptyMeasurement}
    pingMode={false} templateMode={false} templateKind="circle" templateStart={null}
    templateDimensionFt={5} templateAngleDegrees={0} pings={[]} templates={[]} drawings={[]}
    journalDocuments={[]} onJournalDocumentSelect={noop} sharedCamera={null} followSharedCamera={false}
    drawingTool={{ active: false, kind: "rectangle", layer: "under_tokens", audience: "all",
      strokeColor: "#67d1ad", fillColor: "#67d1ad", fillEnabled: false, opacity: 1,
      strokeWidthFt: 1, lineStyle: "solid", locked: false, text: "", fontSizeFt: 2, pointCount: 0, error: null }}
    annotations={[]} selectedAnnotationId="" annotationStatus="live" annotationError={null}
    annotationOperation={null} annotationCanMutate={false} annotationCanManage={() => false}
    currentParticipantId="adventure-player" templatePlacementError={null}
    onTokenSelect={onActor} onTargetSelect={onTarget} onCellSelect={onCell}
    onGridlessPointSelect={noop} onMeasureToggle={noop} onMeasureClear={noop} onPingToggle={noop}
    onTemplateToggle={noop} onTemplateKindChange={noop} onTemplateDimensionChange={noop}
    onTemplateAngleChange={noop} onTemplateCancelStart={noop} onDrawingToggle={noop}
    onDrawingSettingsChange={noop} onDrawingFinish={noop} onDrawingCancel={noop}
    onUpdateSelectedDrawing={noop} onUnlockSelectedDrawing={noop} onAnnotationSelect={noop}
    onRemoveSelected={noop} onClearLocal={noop} onAnnotationRetry={noop}
  />;
}
