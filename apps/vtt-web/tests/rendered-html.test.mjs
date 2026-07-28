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

test("server-renders the branded table loading boundary", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);

  const html = await response.text();
  assert.match(html, /<title>Echo Vault · Solo Table<\/title>/i);
  assert.match(html, /Solo Table \/ Encounter 01/);
  assert.match(html, /Synchronizing the Echo Vault/);
  assert.match(html, /Reading the public table projection/);
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
  assert.match(layout, /Echo Vault · Solo Table/);
  assert.doesNotMatch(page + layout, /codex-preview|_sites-preview|Starter Project/);

  assert.match(client, /GET|method: "GET"/);
  assert.match(client, /\/api\/v1\/session/);
  assert.match(client, /\/api\/v1\/commands/);
  assert.match(client, /vtt\.session_view\.v1/);
  assert.match(client, /dnd\.declare_turn\.v1/);
  assert.doesNotMatch(table + client, /canonical_secret|internal_cursor/);

  assert.match(table, /TacticalMap/);
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
  assert.match(favicon, /#071514/);

  assert.doesNotMatch(packageJson, /react-loading-skeleton/);
  assert.match(packageJson, /"tsx": "4\.22\.1"/);
  await Promise.all([
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
  assert.match(table, /disabled=\{!templateMode && !pingMode && !measureMode && !reachable\}/);
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
  assert.match(table, /disabled=\{!templateMode && !pingMode && !measureMode && !reachable\}/);
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
  assert.match(table, /if \(pingMode \|\| measureMode \|\| templateMode\)/);
  assert.match(table, /disabled=\{!templateMode && !pingMode && !measureMode && !reachable\}/);
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

test("ships a strict GM scene lifecycle manager", async () => {
  const [table, panel, hook, client, css, readme] = await Promise.all([
    readFile(new URL("../app/echo-vault-table.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/vtt-scenes-panel.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/use-vtt-scenes.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/vtt-scenes.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/globals.css", import.meta.url), "utf8"),
    readFile(new URL("../README.md", import.meta.url), "utf8"),
  ]);

  assert.match(table, /<VttScenesPanel/);
  assert.match(panel, /Create scene metadata/);
  assert.match(panel, /Activate/);
  assert.match(panel, /Duplicate/);
  assert.match(panel, /Archive/);
  assert.match(panel, /Export/);
  assert.match(panel, /Import scene/);
  assert.match(panel, /gridless/);
  assert.match(hook, /streamSceneEvents/);
  assert.match(hook, /participant\?\.role !== "gm"/);
  assert.match(client, /vtt\.scene_library_view\.v1/);
  assert.match(client, /vtt\.scene_export\.v1/);
  assert.doesNotMatch(client, /image_blob|asset_path/);
  assert.match(css, /\.scene-panel/);
  assert.match(readme, /scene lifecycle/i);
});
