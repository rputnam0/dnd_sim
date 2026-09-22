import assert from "node:assert/strict";
import { access, readFile } from "node:fs/promises";
import test from "node:test";

const projectRoot = new URL("../", import.meta.url);

async function render() {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);

  return worker.fetch(
    new Request("http://localhost/", {
      headers: { accept: "text/html" },
    }),
    {
      ASSETS: {
        fetch: async () => new Response("Not found", { status: 404 }),
      },
    },
    {
      waitUntil() {},
      passThroughOnException() {},
    },
  );
}

test("server-renders the standalone VTT loading boundary", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);

  const html = await response.text();
  assert.match(html, /<title>DND Sim VTT · Authoritative Tabletop<\/title>/i);
  assert.match(html, /property="og:image" content="https?:\/\/[^\"]+\/og\.png"/i);
  assert.match(html, /name="twitter:card" content="summary_large_image"/i);
  assert.match(html, /Standalone tabletop/);
  assert.match(html, /Joining the active table/);
  assert.match(html, /Reading your authorized table projection/);
  assert.match(html, /role="status"/);
  assert.doesNotMatch(html, /codex-preview|react-loading-skeleton|taking shape/i);
});

test("replaces the starter with the projection-only tactical product", async () => {
  const [page, layout, table, client, css, packageJson, favicon] = await Promise.all([
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/layout.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/echo-vault-table.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/vtt-client.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/globals.css", import.meta.url), "utf8"),
    readFile(new URL("../package.json", import.meta.url), "utf8"),
    readFile(new URL("../public/favicon.svg", import.meta.url), "utf8"),
  ]);

  assert.match(page, /<EchoVaultTable \/>/);
  assert.match(layout, /DND Sim VTT · Authoritative Tabletop/);
  assert.match(layout, /applicationName: "DND Sim VTT"/);
  assert.match(layout, /new URL\("\/og\.png", metadataBase\)/);
  assert.doesNotMatch(page + layout, /codex-preview|_sites-preview|Starter Project/);

  assert.match(client, /GET|method: "GET"/);
  assert.match(client, /\/api\/v1\/session/);
  assert.match(client, /\/api\/v1\/commands/);
  assert.match(client, /vtt\.session_view\.v1/);
  assert.match(client, /dnd\.declare_turn\.v1/);
  assert.doesNotMatch(table + client, /canonical_secret|internal_cursor/);

  assert.match(table, /TacticalMap/);
  assert.match(table, /<VttShell/);
  assert.match(table, /modes: \["prepare"\]/);
  assert.match(table, /roles: \["gm"\]/);
  assert.match(table, /Revision \$\{view\.revision\}/);
  assert.match(table, /Round \$\{view\.projection\.round_number\}/);
  assert.match(table, /Choose destination/);
  assert.match(table, /onCellSelect/);
  assert.match(table, /movementPath/);
  assert.doesNotMatch(table, /new EventSource/);
  assert.match(table, /streamVttEvents/);
  assert.match(client, /"vtt\.event"/);
  assert.match(client, /parseVttEvent/);
  assert.match(table, /Preview turn/);
  assert.match(table, /Commit turn/);
  assert.match(table, /Start encounter/);
  assert.match(table, /Event log/);
  assert.match(css, /grid-template-columns/);
  assert.match(css, /prefers-reduced-motion:\s*reduce/);
  assert.match(css, /\/\* Standalone tabletop workspace \*\//);
  assert.match(css, /"initiative map actions"[\s\S]+?"initiative map dock"/);
  assert.match(css, /@media \(max-width: 820px\)[\s\S]+?"stage"[\s\S]+?"initiative"[\s\S]+?"dock"/);
  assert.match(css, /@media \(forced-colors: active\)/);
  assert.match(css, /--accent-mint:\s*var\(--mint\)/);
  assert.match(css, /--accent-gold:\s*var\(--amber\)/);
  assert.match(css, /--text-strong:\s*var\(--ivory-50\)/);
  assert.match(css, /--text-muted:\s*#[0-9a-f]{6}/i);
  assert.match(favicon, /#071514/);

  assert.doesNotMatch(packageJson, /react-loading-skeleton/);
  assert.match(packageJson, /"name": "dnd-sim-vtt-web"/);
  assert.match(packageJson, /"tsx": "4\.22\.1"/);
  await Promise.all([
    access(new URL("public/og.png", projectRoot)),
    assert.rejects(
      access(new URL("app/_sites-preview/SkeletonPreview.tsx", projectRoot)),
    ),
    assert.rejects(
      access(new URL("app/_sites-preview/preview.css", projectRoot)),
    ),
  ]);
});

test("ships an accessible local-only tactical ruler", async () => {
  const [table, ruler, css, readme] = await Promise.all([
    readFile(new URL("../app/echo-vault-table.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/grid-ruler.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/globals.css", import.meta.url), "utf8"),
    readFile(new URL("../README.md", import.meta.url), "utf8"),
  ]);

  assert.match(table, /\bMeasure\b/);
  assert.match(table, /aria-keyshortcuts="M"/);
  assert.match(table, /aria-pressed=\{measureMode\}/);
  assert.match(table, /Clear measure/);
  assert.match(table, /addEventListener\("keydown"/);
  assert.match(table, /isInteractiveControl/);
  assert.match(table, /is-measure-start/);
  assert.match(table, /is-measure-end/);
  assert.match(table, /measurement-line/);
  assert.match(table, /disabled=\{!drawingTool\.active && !templateMode && !pingMode && !measureMode && !reachable\}/);
  assert.match(
    table,
    /if \(measureMode\) \{\s*setMeasurement\([\s\S]+?nextGridMeasurement[\s\S]+?return;\s*\}\s*handleMovementCellSelect\(cell\)/,
  );
  assert.match(ruler, /Math\.max\(columnDistance, rowDistance\)/);
  assert.doesNotMatch(ruler, /fetch|postCommand|localStorage|sessionStorage/);
  assert.match(css, /\.measure-toggle:focus-visible/);
  assert.match(css, /@media \(prefers-reduced-motion: reduce\)/);
  assert.match(readme, /presentation-only ruler/i);
  assert.match(readme, /never sent to the API or persisted/i);
});

test("drives action and target controls from authoritative turn choices", async () => {
  const [table, client, selection, css] = await Promise.all([
    readFile(new URL("../app/echo-vault-table.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/vtt-client.ts", import.meta.url), "utf8"),
    readFile(
      new URL("../app/turn-choice-selection.ts", import.meta.url),
      "utf8",
    ),
    readFile(new URL("../app/globals.css", import.meta.url), "utf8"),
  ]);

  assert.match(client, /dnd\.turn-choices\.v1/);
  assert.match(client, /selectable_target_ids/);
  assert.match(client, /legal_target_ids/);
  assert.match(table, /projection\.choices/);
  assert.match(table, /selectable_target_ids/);
  assert.match(table, /legal_target_ids/);
  assert.match(table, /Requires movement/);
  assert.match(table, /No available actions/);
  assert.match(table, /initialTurnSelection/);
  assert.match(table, /selectedTargetIdsForChoice/);
  assert.doesNotMatch(table, /function eligibleTargets/);
  assert.doesNotMatch(selection, /\.team|includes\("enemy"\)|includes\("ally"\)/);
  assert.match(css, /\.target-list button\.needs-movement/);
  assert.match(css, /\.target-list button\.is-legal-now/);
  assert.match(css, /\.target-guidance/);
});

test("ships a persisted collaborative ping tool without stealing ruler or movement clicks", async () => {
  const [table, annotations, hook, css, readme] = await Promise.all([
    readFile(new URL("../app/echo-vault-table.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/vtt-annotations.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/use-vtt-annotations.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/globals.css", import.meta.url), "utf8"),
    readFile(new URL("../README.md", import.meta.url), "utf8"),
  ]);

  assert.match(table, /\bPing\b/);
  assert.match(table, /aria-keyshortcuts="P"/);
  assert.match(table, /event\.key\.toLowerCase\(\) !== "p"/);
  assert.match(table, /pingMode/);
  assert.match(table, /ping-marker/);
  assert.match(table, /if \(activePingMode\)[\s\S]+?placePing[\s\S]+?return/);
  assert.match(table, /if \(measureMode\)[\s\S]+?nextGridMeasurement[\s\S]+?return/);
  assert.match(table, /disabled=\{!drawingTool\.active && !templateMode && !pingMode && !measureMode && !reachable\}/);
  assert.match(hook, /getAnnotationsView/);
  assert.match(hook, /streamAnnotationEvents/);
  assert.match(hook, /applyAnnotationEvent/);
  assert.match(annotations, /vtt\.annotations_view\.v1/);
  assert.match(annotations, /vtt\.annotation_request\.v1/);
  assert.match(annotations, /vtt\.annotation_event/);
  assert.doesNotMatch(table + annotations + hook, /localStorage|sessionStorage/);
  assert.match(css, /\.ping-toggle:focus-visible/);
  assert.match(css, /\.ping-marker/);
  assert.match(readme, /shared ping/i);
  assert.match(readme, /optional annotation API/i);
});

test("ships shared area templates with explicit server-backed removal", async () => {
  const [table, annotations, hook, geometry, css, readme] = await Promise.all([
    readFile(new URL("../app/echo-vault-table.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/vtt-annotations.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/use-vtt-annotations.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/vtt-template-geometry.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/globals.css", import.meta.url), "utf8"),
    readFile(new URL("../README.md", import.meta.url), "utf8"),
  ]);

  assert.match(table, /\bTemplate\b/);
  assert.match(table, /aria-keyshortcuts="T"/);
  assert.match(table, /circle|Circle/);
  assert.match(table, /cone|Cone/);
  assert.match(table, /line|Line/);
  assert.match(table, /cube|Cube/);
  assert.match(table, /type="number"/);
  assert.match(table, /if \(activeTemplateMode\)[\s\S]+?buildAreaTemplateAnnotation[\s\S]+?return/);
  assert.match(table, /if \(pingMode \|\| measureMode \|\| templateMode \|\| drawingTool\.active\)/);
  assert.match(table, /disabled=\{!drawingTool\.active && !templateMode && !pingMode && !measureMode && !reachable\}/);
  assert.match(table, /template-overlay/);
  assert.match(hook, /removeAnnotation/);
  assert.match(hook, /clearLocalAnnotations/);
  assert.match(hook, /annotation_stale_revision/);
  assert.match(annotations, /buildAnnotationDeleteRequest/);
  assert.match(annotations, /command_type: "delete"/);
  assert.match(geometry, /cellToFeet/);
  assert.match(css, /\.template-toggle:focus-visible/);
  assert.match(css, /\.template-overlay/);
  assert.match(readme, /area templates/i);
  assert.match(readme, /server-backed deletion/i);
  assert.match(readme, /protected browser auth/i);
});

test("ships durable layered drawings with keyboard-operable authoring", async () => {
  const [table, annotations, drawings, layer, css, readme] = await Promise.all([
    readFile(new URL("../app/echo-vault-table.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/vtt-annotations.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/vtt-drawings.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/vtt-drawing-layer.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/globals.css", import.meta.url), "utf8"),
    readFile(new URL("../README.md", import.meta.url), "utf8"),
  ]);

  assert.match(table, /aria-keyshortcuts="D"/);
  assert.match(table, /Unlock selected drawing/);
  assert.match(table, /isLockedDrawingAnnotation\(selectedAnnotation\)/);
  assert.match(table, /unlockedOwnedAnnotationCount/);
  assert.match(table, /Freehand path/);
  assert.match(table, /Rectangle/);
  assert.match(table, /Ellipse/);
  assert.match(table, /Arrow/);
  assert.match(table, /Text label/);
  assert.match(table, /Audience/);
  assert.match(table, /Under tokens/);
  assert.match(table, /Over tokens/);
  assert.match(table, /Update selected drawing/);
  assert.match(table, /drawingTool\.active[\s\S]+?add shared drawing point/);
  assert.match(annotations, /freehand_drawing/);
  assert.match(annotations, /shape_drawing/);
  assert.match(annotations, /arrow_drawing/);
  assert.match(annotations, /text_drawing/);
  assert.match(drawings, /feetToBoardPixel/);
  assert.match(layer, /drawing-\$\{layer\.replace\("_", "-"\)\}/);
  assert.match(layer, /data-plain-text="true"/);
  assert.doesNotMatch(layer, /dangerouslySetInnerHTML/);
  assert.match(css, /\.drawing-toggle:focus-visible/);
  assert.match(css, /\.drawing-under-tokens/);
  assert.match(css, /\.drawing-over-tokens/);
  assert.match(css, /prefers-reduced-motion:\s*reduce/);
  assert.match(readme, /durable layered drawings/i);
});

test("ships accessible durable plain-text chat without fabricated presentation data", async () => {
  const [table, panel, client, hook, css, readme] = await Promise.all([
    readFile(new URL("../app/echo-vault-table.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/vtt-chat-panel.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/vtt-chat.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/use-vtt-chat.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/globals.css", import.meta.url), "utf8"),
    readFile(new URL("../README.md", import.meta.url), "utf8"),
  ]);

  assert.match(table, /<VttChatPanel[\s\S]+?table=\{tableIdentity\}/);
  assert.match(panel, /role="log"/);
  assert.match(panel, /<form/);
  assert.match(panel, /<textarea/);
  assert.match(panel, /Array\.from\(draft\)\.length/);
  assert.match(panel, /characterCount <= MAX_CHAT_TEXT_LENGTH/);
  assert.doesNotMatch(panel, /maxLength=/);
  assert.match(panel, /setDraft\(\(current\) =>[\s\S]+?current === submittedText/);
  assert.match(panel, /chat\.canDeleteMessage\(message\.author_id\)/);
  assert.match(panel, /Audience/);
  assert.match(panel, /chatAudienceChoices/);
  assert.match(panel, /deleteMessage/);
  assert.match(panel, /\{message\.text\}/);
  assert.match(client, /vtt\.chat_view\.v1/);
  assert.match(client, /buildChatPostRequest/);
  assert.match(client, /buildChatDeleteRequest/);
  assert.match(hook, /getChatView/);
  assert.match(hook, /streamChatEvents/);
  assert.match(hook, /chat_stale_revision/);
  assert.match(hook, /event === null/);
  assert.match(css, /\.chat-message-text[\s\S]+?white-space:\s*pre-wrap/);
  assert.match(readme, /plain-text chat/i);
  assert.match(readme, /no timestamps/i);
  assert.doesNotMatch(
    panel + client + hook,
    /dangerouslySetInnerHTML|\.innerHTML|\bmarked\b|markdown-it|new Date\(|Date\.now\(|timestamp/i,
  );
});

test("ships protected participant identity without persisting or leaking credentials", async () => {
  const [table, access, gate, transport, client, annotations, chat] =
    await Promise.all([
      readFile(new URL("../app/echo-vault-table.tsx", import.meta.url), "utf8"),
      readFile(new URL("../app/vtt-access.ts", import.meta.url), "utf8"),
      readFile(new URL("../app/vtt-access-gate.tsx", import.meta.url), "utf8"),
      readFile(new URL("../app/vtt-transport.ts", import.meta.url), "utf8"),
      readFile(new URL("../app/vtt-client.ts", import.meta.url), "utf8"),
      readFile(new URL("../app/vtt-annotations.ts", import.meta.url), "utf8"),
      readFile(new URL("../app/vtt-chat.ts", import.meta.url), "utf8"),
    ]);

  assert.match(access, /vtt\.table_view\.v1/);
  assert.match(access, /\/api\/v1\/table/);
  assert.match(gate, /type="password"/);
  assert.match(gate, /never placed in a URL/);
  assert.match(transport, /authorization = `Bearer \$\{bearerToken\}`/);
  assert.match(table, /canControlActor/);
  assert.match(table, /current_participant/);
  assert.match(client, /streamVttEvents/);
  assert.match(annotations, /buildVttRequestHeaders/);
  assert.match(chat, /buildVttRequestHeaders/);
  assert.doesNotMatch(
    table + access + gate + transport + client + annotations + chat,
    /localStorage|sessionStorage|bearerToken=.*(?:\?|&)|token=.*(?:\?|&)/,
  );
});

test("renders the authoritative token projection and ships accessible GM lifecycle controls", async () => {
  const [table, panel, hook, client, css] = await Promise.all([
    readFile(new URL("../app/echo-vault-table.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/vtt-tokens-panel.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/use-vtt-tokens.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/vtt-tokens.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/globals.css", import.meta.url), "utf8"),
  ]);

  assert.match(table, /useVttTokens/);
  assert.match(table, /tokens={sharedTokens\.view\?\.tokens \?\? \[\]}/);
  assert.match(table, /Loading authoritative token projection/);
  assert.match(table, /role="status"/);
  assert.doesNotMatch(table, /authoritativeTokens === undefined/);
  assert.match(table, /<VttTokensPanel/);
  assert.match(table, /token\.pose\.position_ft/);
  assert.match(table, /token\.nameplate/);
  assert.match(panel, /Token workshop/);
  assert.match(panel, /<form/);
  assert.match(panel, /Create token/);
  assert.match(panel, /Update token/);
  assert.match(panel, /Duplicate/);
  assert.match(panel, /Delete/);
  assert.match(panel, /type="number"/);
  assert.match(panel, /aria-live="polite"/);
  assert.match(hook, /streamTokenEvents/);
  assert.match(client, /vtt\.token_view\.v1/);
  assert.match(css, /\.token-panel/);
  assert.doesNotMatch(table + panel + hook + client, /localStorage|sessionStorage/);
});

test("ships a strict GM scene lifecycle manager with private map uploads", async () => {
  const [table, panel, hook, client, calibration, assetClient, assetHook, css, readme] = await Promise.all([
    readFile(new URL("../app/echo-vault-table.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/vtt-scenes-panel.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/use-vtt-scenes.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/vtt-scenes.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/vtt-board-calibration.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/vtt-map-assets.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/use-vtt-map-assets.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/globals.css", import.meta.url), "utf8"),
    readFile(new URL("../README.md", import.meta.url), "utf8"),
  ]);

  assert.match(table, /<VttScenesPanel/);
  assert.match(table, /backgroundImage/);
  assert.match(table, /data-map-asset-id/);
  assert.match(panel, /Create scene/);
  assert.match(panel, /map attached/);
  assert.match(panel, /Upload map image/);
  assert.match(panel, /Attach and calibrate map/);
  assert.match(panel, /Flat-top hex/);
  assert.match(panel, /Pointy-top hex/);
  assert.match(panel, /Origin X px/);
  assert.match(panel, /Feet \/ step/);
  assert.match(panel, /type="file"/);
  assert.match(panel, /Activate/);
  assert.match(panel, /Duplicate/);
  assert.match(panel, /Archive/);
  assert.match(panel, /Choose the next active scene/);
  assert.match(panel, /Confirm archive/);
  assert.match(panel, /Export/);
  assert.match(panel, /Import scene/);
  assert.match(panel, /gridless/);
  assert.match(client, /parseBoardCalibration/);
  assert.match(calibration, /roundAxial/);
  assert.match(calibration, /enumerateBoardCells/);
  assert.match(calibration, /pixelDistanceFeet/);
  assert.match(calibration, /moveGridlessCursor/);
  assert.match(table, /data-board-topology/);
  assert.match(table, /handleGridlessBoardClick/);
  assert.match(table, /handleGridlessBoardKeyDown/);
  assert.match(table, /gridless-keyboard-instructions/);
  assert.match(table, /active_board/);
  assert.match(table, /boardPresentation\.status === "error" \? "alert" : "status"/);
  assert.match(table, /Gridless ruler/);
  assert.match(table, /square-board tools/);
  assert.doesNotMatch(table, /topology === "gridless" \? "square"/);
  assert.doesNotMatch(table, /presentedCalibration\([^\n]+,\s*null\)/);
  assert.doesNotMatch(table, /legacyBoardCalibration/);
  assert.match(css, /\.calibrated-board\.topology-hex-flat/);
  assert.match(css, /\.calibrated-board\.topology-hex-pointy/);
  assert.match(hook, /streamSceneEvents/);
  assert.match(hook, /setError\(null\)/);
  assert.match(hook, /participant\?\.role !== "gm"/);
  assert.match(client, /vtt\.scene_library_view\.v1/);
  assert.match(client, /vtt\.scene_export\.v1/);
  assert.match(client, /vtt\.scene_map_asset\.v1/);
  assert.match(client, /safe same-origin map asset/);
  assert.doesNotMatch(client, /image_blob/);
  assert.match(assetClient, /\/api\/v1\/map-assets/);
  assert.match(assetClient, /fetchAuthenticatedMapAsset/);
  assert.match(assetClient, /crypto\.subtle\.digest/);
  assert.match(assetHook, /URL\.revokeObjectURL/);
  assert.doesNotMatch(assetClient + assetHook, /localStorage|sessionStorage/);
  assert.match(css, /\.scene-panel/);
  assert.match(readme, /scene lifecycle/i);
});

test("ships safe multi-client participant presence without durable browser credentials", async () => {
  const [table, panel, client, hook, css, readme] = await Promise.all([
    readFile(new URL("../app/echo-vault-table.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/vtt-presence-panel.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/vtt-presence.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/use-vtt-presence.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/globals.css", import.meta.url), "utf8"),
    readFile(new URL("../README.md", import.meta.url), "utf8"),
  ]);

  assert.match(table, /<VttPresencePanel/);
  assert.match(panel, /Participant presence/);
  assert.match(panel, /Online|online/);
  assert.match(panel, /Away/);
  assert.match(panel, /Offline/);
  assert.match(client, /vtt\.presence_view\.v1/);
  assert.match(client, /vtt\.presence_heartbeat_request\.v1/);
  assert.match(client, /vtt\.presence_changed/);
  assert.match(client, /assertPresenceViewMatchesTable/);
  assert.match(hook, /streamPresenceEvents/);
  assert.match(hook, /presence_stale_revision/);
  assert.match(hook, /crypto\.randomUUID\(\)/);
  assert.match(hook, /setError\(null\)/);
  assert.match(css, /\.presence-dot-online/);
  assert.match(css, /\.presence-dot-away/);
  assert.match(css, /\.presence-dot-offline/);
  assert.match(readme, /participant presence/i);
  assert.doesNotMatch(
    table + panel + client + hook,
    /localStorage|sessionStorage|bearerToken=.*(?:\?|&)|token=.*(?:\?|&)/,
  );
});

test("ships server-projected fog with fail-closed masking and accessible GM authoring", async () => {
  const [table, client, hook, panel, mask, css, readme] = await Promise.all([
    readFile(new URL("../app/echo-vault-table.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/vtt-visibility.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/use-vtt-visibility.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/vtt-visibility-panel.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/vtt-visibility-mask.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/globals.css", import.meta.url), "utf8"),
    readFile(new URL("../README.md", import.meta.url), "utf8"),
  ]);

  assert.match(table, /useVttVisibility/);
  assert.match(table, /sharedVisibility\.projection\?\.tokens/);
  assert.match(table, /<VttVisibilityMask/);
  assert.match(table, /<VttVisibilityPanel/);
  assert.match(hook, /getVisibilityProjection/);
  assert.match(hook, /streamVisibilityEvents/);
  assert.match(hook, /getVisibilityPreview/);
  assert.match(hook, /input\.sceneRevision/);
  assert.match(hook, /input\.tokenRevision/);
  assert.match(hook, /input\.encounterRevision/);
  assert.match(hook, /setProjection\(null\)/);
  assert.match(hook, /setPreview\(null\)/);
  assert.match(hook, /setExpectedVisibilityRevision\(event\.revision\)/);
  assert.match(client, /vtt\.visibility_projection\.v1/);
  assert.match(client, /visibilityProjectionMatchesSources/);
  assert.match(client, /vtt\.visibility_catalog_view\.v1/);
  assert.match(client, /vtt\.visibility_changed/);
  assert.match(mask, /is-fail-closed/);
  assert.match(mask, /paintVisibilityMask/);
  assert.match(mask, /visibilityProjectionMatchesSources\(projection, sources\)/);
  assert.match(mask, /fillRect\(0, 0, width, height\)/);
  assert.match(panel, /<form/);
  assert.match(panel, /<fieldset/);
  assert.match(panel, /Save environment/);
  assert.match(panel, /Add barrier/);
  assert.match(panel, /Add light/);
  assert.match(panel, /Save token senses/);
  assert.match(panel, /Append fog operation/);
  assert.match(panel, /Undo last fog/);
  assert.match(panel, /aria-label=\{`\$\{record\.portal_state/);
  assert.match(css, /\.visibility-mask\.is-ready/);
  assert.match(css, /\.visibility-panel (?:input|label)/);
  assert.match(css, /@media \(prefers-reduced-motion: reduce\)[\s\S]+?\.visibility-mask/);
  assert.match(readme, /fog|visibility/i);
  assert.doesNotMatch(client + hook + mask, /localStorage|sessionStorage|raw_barriers/);
});

test("renders strict engine-authored roll cards without client dice generation", async () => {
  const [table, card, codec, css] = await Promise.all([
    readFile(new URL("../app/echo-vault-table.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/vtt-roll-card.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/vtt-roll-cards.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/globals.css", import.meta.url), "utf8"),
  ]);

  assert.match(table, /rollCardFromEvent/);
  assert.match(table, /<VttRollCardArticle/);
  assert.match(card, /<article/);
  assert.match(card, /<details>/);
  assert.match(card, /<summary>Show generated dice<\/summary>/);
  assert.match(card, /Authoritative preview/);
  assert.match(codec, /vtt\.roll_card\.v1/);
  assert.match(codec, /applied_damage/);
  assert.match(css, /\.roll-card/);
  assert.doesNotMatch(table + card + codec, /Math\.random|crypto\.getRandomValues|rollDice/);
});
