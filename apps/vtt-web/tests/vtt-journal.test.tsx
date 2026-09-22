import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { JournalDocumentContent } from "../app/vtt-journal-panel";
import {
  applyJournalEvent,
  buildJournalDeleteDocumentRequest,
  buildJournalDeleteFolderRequest,
  buildJournalPutDocumentRequest,
  buildJournalPutFolderRequest,
  journalViewMatchesIdentity,
  parseJournalDocument,
  parseJournalSseBlock,
  parseJournalView,
} from "../app/vtt-journal";

const document = {
  schema_version: "vtt.journal_document.v1",
  document_id: "vault-key",
  document_type: "handout",
  folder_id: null,
  title: "Vault Key",
  audience: ["all"],
  tags: ["lore"],
  favorite: true,
  blocks: [
    {
      schema_version: "vtt.journal_block.v1",
      block_type: "heading",
      level: 2,
      text: "Northern seal",
    },
    {
      schema_version: "vtt.journal_block.v1",
      block_type: "paragraph",
      text: "Hold <script>alert(1)</script> against the glass.",
    },
    {
      schema_version: "vtt.journal_block.v1",
      block_type: "bullet_list",
      items: ["Turn once", "Speak softly"],
    },
    {
      schema_version: "vtt.journal_block.v1",
      block_type: "document_link",
      document_id: "vault-map",
      label: "Open the map",
    },
  ],
  map_pin: {
    schema_version: "vtt.journal_map_pin.v1",
    scene_id: "echo-vault",
    position: { x_ft: 7.5, y_ft: 7.5, z_ft: 0 },
    color: "#5eead4",
  },
} as const;

const mapDocument = {
  ...document,
  document_id: "vault-map",
  title: "Vault Map",
  favorite: false,
  blocks: [{
    schema_version: "vtt.journal_block.v1",
    block_type: "paragraph",
    text: "Map text",
  }],
  map_pin: null,
} as const;

test("strictly decodes inert journal blocks, view identity, and requests", () => {
  const parsed = parseJournalDocument(document);
  const view = parseJournalView({
    schema_version: "vtt.journal_view.v1",
    session_id: "session-a",
    table_id: "table-a",
    revision: 2,
    folders: [],
    documents: [document, mapDocument],
  });
  assert.equal(journalViewMatchesIdentity(view, { sessionId: "session-a", tableId: "table-a" }), true);
  assert.equal(journalViewMatchesIdentity(view, { sessionId: "session-a", tableId: "other" }), false);
  assert.equal(buildJournalPutDocumentRequest({ sessionId: "session-a", tableId: "table-a", expectedRevision: 2, commandId: "put", document: parsed }).command.command_type, "put_document");
  assert.equal(buildJournalDeleteDocumentRequest({ sessionId: "session-a", tableId: "table-a", expectedRevision: 2, commandId: "delete", documentId: "vault-key" }).command.command_type, "delete_document");
  assert.equal(buildJournalPutFolderRequest({ sessionId: "session-a", tableId: "table-a", expectedRevision: 2, commandId: "put-folder", folder: { schema_version: "vtt.journal_folder.v1", folder_id: "lore", parent_folder_id: null, name: "Lore" } }).command.command_type, "put_folder");
  assert.equal(buildJournalDeleteFolderRequest({ sessionId: "session-a", tableId: "table-a", expectedRevision: 2, commandId: "delete-folder", folderId: "lore" }).command.command_type, "delete_folder");
  assert.throws(() => parseJournalDocument({ ...document, extra: "secret" }), /unexpected field/i);
  assert.throws(() => parseJournalDocument({ ...document, tags: ["zeta", "alpha"] }), /sorted/i);
  assert.throws(() => parseJournalDocument({ ...document, blocks: [{ schema_version: "vtt.journal_block.v1", block_type: "paragraph", text: "bad\u0000text" }] }), /control/i);
  assert.throws(() => parseJournalDocument({ ...document, audience: ["javascript:alert(1)"] }), /audience/i);
  assert.throws(() => parseJournalDocument({ ...document, audience: [`participant:${"x".repeat(129)}`] }), /128/i);
  assert.throws(() => parseJournalDocument({ ...document, tags: ["x".repeat(65)] }), /64/i);
  assert.throws(() => parseJournalDocument({ ...document, title: "x", blocks: [{ schema_version: "vtt.journal_block.v1", block_type: "paragraph", text: "x".repeat(50_000) }] }), /50,000/i);
  assert.throws(() => parseJournalView({ ...view, folders: [{ schema_version: "vtt.journal_folder.v1", folder_id: "child", parent_folder_id: "missing", name: "Child" }] }), /folder/i);
});

test("rejects colon-bearing audience IDs while accepting the exact ID bound", () => {
  const baseView = {
    schema_version: "vtt.journal_view.v1",
    session_id: "session-a",
    table_id: "table-a",
    revision: 1,
    folders: [],
  };
  const exactCodePointBound = "🐉".repeat(128);
  for (const selectorKind of ["participant", "actor"] as const) {
    const selector = `${selectorKind}:${exactCodePointBound}`;
    const valid = { ...document, audience: [selector] };
    assert.equal(parseJournalView({ ...baseView, documents: [valid, mapDocument] }).documents[0].audience[0], selector);
    assert.throws(() => parseJournalView({ ...baseView, documents: [{ ...document, audience: [`${selectorKind}:a:b`] }, mapDocument] }), /must not contain a colon/);
  }
});

test("uses locale-independent code-point ordering for received and applied documents", () => {
  const upper = { ...mapDocument, document_id: "unicode-upper", title: "Zebra" };
  const lower = { ...mapDocument, document_id: "unicode-lower", title: "äther" };
  assert.doesNotThrow(() => parseJournalView({
    schema_version: "vtt.journal_view.v1",
    session_id: "session-a",
    table_id: "table-a",
    revision: 1,
    folders: [],
    documents: [document, mapDocument, upper, lower],
  }));
});

test("renders rich blocks as escaped React text and keyboard-operable internal links", () => {
  const html = renderToStaticMarkup(createElement(JournalDocumentContent, {
    document: parseJournalDocument(document),
    onOpenDocument: () => undefined,
  }));
  assert.match(html, /<h4>Northern seal<\/h4>/);
  assert.match(html, /Hold &lt;script&gt;alert\(1\)&lt;\/script&gt;/);
  assert.match(html, /<button[^>]+type="button"[^>]*>Open the map<\/button>/);
  assert.doesNotMatch(html, /<script>/);
  assert.doesNotMatch(html, /dangerouslySetInnerHTML/);
});

test("applies reconnectable projected puts and privacy tombstones", () => {
  const projectedDocument = {
    ...document,
    blocks: document.blocks.filter((block) => block.block_type !== "document_link"),
  };
  const view = parseJournalView({
    schema_version: "vtt.journal_view.v1",
    session_id: "session-a",
    table_id: "table-a",
    revision: 1,
    folders: [],
    documents: [projectedDocument],
  });
  const block = [
    "id: 2",
    "event: vtt.journal_event",
    `data: ${JSON.stringify({ schema_version: "vtt.journal_event.v1", event_type: "document_deleted", table_id: "table-a", event_id: "table-a:journal:2", sequence: 2, revision: 2, command_id: "narrow", document: projectedDocument })}`,
    "",
    "",
  ].join("\n");
  const event = parseJournalSseBlock(block);
  assert.ok(event);
  assert.deepEqual(applyJournalEvent(view, event).documents, []);
});

test("removes now-hidden target links when a projected target tombstone arrives", () => {
  const source = parseJournalDocument(document);
  const target = parseJournalDocument(mapDocument);
  const view = parseJournalView({
    schema_version: "vtt.journal_view.v1",
    session_id: "session-a",
    table_id: "table-a",
    revision: 1,
    folders: [],
    documents: [source, target],
  });
  const event = parseJournalSseBlock([
    "id: 2",
    "event: vtt.journal_event",
    `data: ${JSON.stringify({ schema_version: "vtt.journal_event.v1", event_type: "document_deleted", table_id: "table-a", event_id: "table-a:journal:2", sequence: 2, revision: 2, command_id: "narrow-target", document: target })}`,
    "",
    "",
  ].join("\n"));
  assert.ok(event);
  const next = applyJournalEvent(view, event);
  assert.deepEqual(next.documents.map((item) => item.document_id), ["vault-key"]);
  assert.deepEqual(next.documents[0]?.blocks.map((block) => block.block_type), [
    "heading", "paragraph", "bullet_list",
  ]);
});
