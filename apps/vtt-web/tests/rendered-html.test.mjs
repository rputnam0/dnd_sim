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
