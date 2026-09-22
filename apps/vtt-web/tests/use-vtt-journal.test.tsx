import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import TestRenderer, { act } from "react-test-renderer";

import { useVttJournal } from "../app/use-vtt-journal";
import type { VttTableParticipant } from "../app/vtt-access";
import type { JournalDocument, JournalView } from "../app/vtt-journal";

const reactTestEnvironment: typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean } = globalThis;
reactTestEnvironment.IS_REACT_ACT_ENVIRONMENT = true;

const document: JournalDocument = {
  schema_version: "vtt.journal_document.v1",
  document_id: "vault-key",
  document_type: "handout",
  folder_id: null,
  title: "Vault Key",
  audience: ["all"],
  tags: ["lore"],
  favorite: false,
  blocks: [{
    schema_version: "vtt.journal_block.v1",
    block_type: "paragraph",
    text: "The glass key opens the seal.",
  }],
  map_pin: null,
};

function view(revision: number): JournalView {
  return {
    schema_version: "vtt.journal_view.v1",
    session_id: "session-a",
    table_id: "table-a",
    revision,
    folders: [],
    documents: [document],
  };
}

type JournalHook = ReturnType<typeof useVttJournal>;

const player: VttTableParticipant = {
  schema_version: "vtt.participant.v1",
  participant_id: "player",
  display_name: "Player",
  role: "player",
  owned_actor_ids: [],
};

const gm: VttTableParticipant = {
  schema_version: "vtt.participant.v1",
  participant_id: "gm",
  display_name: "GM",
  role: "gm",
  owned_actor_ids: [],
};

function Harness({
  observe,
  participant = player,
  bearerToken = "journal-token-a-0001",
}: {
  observe: (journal: JournalHook) => void;
  participant?: VttTableParticipant;
  bearerToken?: string;
}) {
  const journal = useVttJournal({
    sessionId: "session-a",
    tableId: "table-a",
    bearerToken,
    participant,
  });
  observe(journal);
  return createElement("output", null, `${journal.status}:${journal.documents.length}`);
}

test("searched journal fails closed immediately on an event until exact rehydration", async () => {
  const originalFetch = globalThis.fetch;
  const streams: ReadableStreamDefaultController<Uint8Array>[] = [];
  let getCount = 0;
  let resolveThirdGet: ((response: Response) => void) | null = null;
  const encoder = new TextEncoder();
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.includes("journal-events")) {
      const stream = new ReadableStream<Uint8Array>({
        start(controller) {
          streams.push(controller);
          init?.signal?.addEventListener("abort", () => {
            try {
              controller.error(new DOMException("Aborted", "AbortError"));
            } catch {
              // The stream may already be closed by test teardown.
            }
          }, { once: true });
        },
      });
      return new Response(stream, { status: 200, headers: { "content-type": "text/event-stream" } });
    }
    getCount += 1;
    if (getCount === 3) {
      return await new Promise<Response>((resolve) => { resolveThirdGet = resolve; });
    }
    return new Response(JSON.stringify(view(1)), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  }) as typeof fetch;

  let current!: JournalHook;
  let renderer!: TestRenderer.ReactTestRenderer;
  try {
    await act(async () => {
      renderer = TestRenderer.create(createElement(Harness, {
        observe: (journal: JournalHook) => { current = journal; },
      }));
      await Promise.resolve();
      await Promise.resolve();
    });
    assert.equal(current.error, null);
    assert.equal(current.status, "live");
    assert.equal(current.documents.length, 1);

    await act(async () => {
      current.setQuery("vault");
      await Promise.resolve();
      await Promise.resolve();
    });
    assert.equal(current.status, "live");
    assert.equal(streams.length, 2);

    const event = {
      schema_version: "vtt.journal_event.v1",
      event_type: "document_put",
      table_id: "table-a",
      event_id: "table-a:journal:2",
      sequence: 2,
      revision: 2,
      command_id: "update",
      document: { ...document, title: "Vault Key Revised" },
    };
    await act(async () => {
      streams[1].enqueue(encoder.encode([
        "id: 2",
        "event: vtt.journal_event",
        `data: ${JSON.stringify(event)}`,
        "",
        "",
      ].join("\n")));
      await Promise.resolve();
      await Promise.resolve();
    });
    assert.equal(getCount, 3);
    assert.equal(current.status, "loading");
    assert.equal(current.documents.length, 0);

    await act(async () => {
      assert.ok(resolveThirdGet);
      resolveThirdGet(new Response(JSON.stringify(view(2)), {
        status: 200,
        headers: { "content-type": "application/json" },
      }));
      await Promise.resolve();
      await Promise.resolve();
    });
    assert.equal(current.status, "live");
    assert.equal(current.documents.length, 1);
    assert.equal(current.view?.revision, 2);
  } finally {
    await act(async () => renderer?.unmount());
    globalThis.fetch = originalFetch;
  }
});

test("successful mutation hydration keeps the existing live stream available", async () => {
  const originalFetch = globalThis.fetch;
  const streams: ReadableStreamDefaultController<Uint8Array>[] = [];
  let getCount = 0;
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.includes("journal-events")) {
      const stream = new ReadableStream<Uint8Array>({
        start(controller) {
          streams.push(controller);
          init?.signal?.addEventListener("abort", () => {
            try { controller.error(new DOMException("Aborted", "AbortError")); } catch { /* closed */ }
          }, { once: true });
        },
      });
      return new Response(stream, { status: 200, headers: { "content-type": "text/event-stream" } });
    }
    if (init?.method === "POST") {
      return new Response("{}", { status: 200, headers: { "content-type": "application/json" } });
    }
    getCount += 1;
    const projected = view(getCount === 1 ? 1 : 2);
    if (getCount > 1) projected.documents = [{ ...document, title: "Vault Key Revised" }];
    return new Response(JSON.stringify(projected), { status: 200, headers: { "content-type": "application/json" } });
  }) as typeof fetch;

  let current!: JournalHook;
  let renderer!: TestRenderer.ReactTestRenderer;
  try {
    await act(async () => {
      renderer = TestRenderer.create(createElement(Harness, {
        participant: gm,
        observe: (journal: JournalHook) => { current = journal; },
      }));
      await Promise.resolve();
      await Promise.resolve();
    });
    assert.equal(current.status, "live");
    assert.equal(current.documents.length, 1);
    await act(async () => {
      await current.saveDocument({ ...document, title: "Vault Key Revised" });
    });
    assert.equal(getCount, 2);
    assert.equal(streams.length, 1);
    assert.equal(current.status, "live");
    assert.equal(current.available, true);
    assert.equal(current.documents[0]?.title, "Vault Key Revised");
  } finally {
    await act(async () => renderer?.unmount());
    globalThis.fetch = originalFetch;
  }
});

test("principal changes synchronously hide a prior GM projection before rehydration", async () => {
  const originalFetch = globalThis.fetch;
  let getCount = 0;
  let resolvePlayerGet: ((response: Response) => void) | null = null;
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.includes("journal-events")) {
      const stream = new ReadableStream<Uint8Array>({
        start(controller) {
          init?.signal?.addEventListener("abort", () => {
            try { controller.error(new DOMException("Aborted", "AbortError")); } catch { /* closed */ }
          }, { once: true });
        },
      });
      return new Response(stream, { status: 200, headers: { "content-type": "text/event-stream" } });
    }
    getCount += 1;
    if (getCount === 2) return await new Promise<Response>((resolve) => { resolvePlayerGet = resolve; });
    return new Response(JSON.stringify({
      ...view(1),
      folders: [{ schema_version: "vtt.journal_folder.v1", folder_id: "gm-secrets", parent_folder_id: null, name: "GM Secrets" }],
      documents: [{ ...document, folder_id: "gm-secrets", title: "GM Secret" }],
    }), { status: 200, headers: { "content-type": "application/json" } });
  }) as typeof fetch;

  let current!: JournalHook;
  let renderer!: TestRenderer.ReactTestRenderer;
  const observe = (journal: JournalHook) => { current = journal; };
  try {
    await act(async () => {
      renderer = TestRenderer.create(createElement(Harness, { participant: gm, bearerToken: "journal-gm-token-0001", observe }));
      await Promise.resolve();
      await Promise.resolve();
    });
    assert.equal(current.status, "live");
    assert.equal(current.documents[0]?.title, "GM Secret");
    assert.equal(current.folders[0]?.name, "GM Secrets");

    await act(async () => {
      renderer.update(createElement(Harness, { participant: player, bearerToken: "journal-player-token-0001", observe }));
      await Promise.resolve();
    });
    assert.equal(getCount, 2);
    assert.equal(current.status, "loading");
    assert.equal(current.available, false);
    assert.equal(current.view, null);
    assert.equal(current.documents.length, 0);
    assert.deepEqual(current.folders, []);

    await act(async () => {
      assert.ok(resolvePlayerGet);
      resolvePlayerGet(new Response(JSON.stringify({ ...view(1), documents: [] }), { status: 200, headers: { "content-type": "application/json" } }));
      await Promise.resolve();
      await Promise.resolve();
    });
    assert.equal(current.status, "live");
    assert.equal(current.documents.length, 0);
  } finally {
    await act(async () => renderer?.unmount());
    globalThis.fetch = originalFetch;
  }
});

test("participant SSE broadening rehydrates so formerly hidden links converge with current GET", async () => {
  const originalFetch = globalThis.fetch;
  let getCount = 0;
  let streamController: ReadableStreamDefaultController<Uint8Array> | null = null;
  let resolveSecondGet: ((response: Response) => void) | null = null;
  const sourceWithoutLink = { ...document, document_id: "source", title: "Source" };
  const target = { ...document, document_id: "target", title: "Target" };
  const sourceWithLink: JournalDocument = {
    ...sourceWithoutLink,
    blocks: [
      ...sourceWithoutLink.blocks,
      { schema_version: "vtt.journal_block.v1", block_type: "document_link", document_id: "target", label: "Open target" },
    ],
  };
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.includes("journal-events")) {
      const stream = new ReadableStream<Uint8Array>({
        start(controller) {
          streamController = controller;
          init?.signal?.addEventListener("abort", () => {
            try { controller.error(new DOMException("Aborted", "AbortError")); } catch { /* closed */ }
          }, { once: true });
        },
      });
      return new Response(stream, { status: 200, headers: { "content-type": "text/event-stream" } });
    }
    getCount += 1;
    if (getCount === 2) return await new Promise<Response>((resolve) => { resolveSecondGet = resolve; });
    return new Response(JSON.stringify({ ...view(1), documents: [sourceWithoutLink] }), { status: 200, headers: { "content-type": "application/json" } });
  }) as typeof fetch;

  let current!: JournalHook;
  let renderer!: TestRenderer.ReactTestRenderer;
  try {
    await act(async () => {
      renderer = TestRenderer.create(createElement(Harness, {
        observe: (journal: JournalHook) => { current = journal; },
      }));
      await Promise.resolve();
      await Promise.resolve();
    });
    assert.equal(current.status, "live");
    assert.deepEqual(current.documents[0]?.blocks.map((block) => block.block_type), ["paragraph"]);

    await act(async () => {
      assert.ok(streamController);
      streamController.enqueue(new TextEncoder().encode([
        "id: 2",
        "event: vtt.journal_event",
        `data: ${JSON.stringify({ schema_version: "vtt.journal_event.v1", event_type: "document_put", table_id: "table-a", event_id: "table-a:journal:2", sequence: 2, revision: 2, command_id: "share-target", document: target })}`,
        "",
        "",
      ].join("\n")));
      await Promise.resolve();
      await Promise.resolve();
    });
    assert.equal(current.status, "loading");
    assert.equal(current.documents.length, 0);
    assert.equal(getCount, 2);

    await act(async () => {
      assert.ok(resolveSecondGet);
      resolveSecondGet(new Response(JSON.stringify({ ...view(2), documents: [sourceWithLink, target] }), { status: 200, headers: { "content-type": "application/json" } }));
      await Promise.resolve();
      await Promise.resolve();
    });
    assert.equal(current.status, "live");
    assert.deepEqual(current.documents.map((item) => item.document_id), ["source", "target"]);
    assert.deepEqual(current.documents[0]?.blocks.map((block) => block.block_type), ["paragraph", "document_link"]);
  } finally {
    await act(async () => renderer?.unmount());
    globalThis.fetch = originalFetch;
  }
});
