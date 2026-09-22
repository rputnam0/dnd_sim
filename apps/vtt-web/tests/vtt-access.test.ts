import assert from "node:assert/strict";
import test from "node:test";

import {
  canControlActor,
  canDeleteParticipantRecord,
  chatAudienceChoices,
  getTableView,
  parseTableView,
} from "../app/vtt-access";
import {
  buildVttRequestHeaders,
  normalizeVttBearerToken,
} from "../app/vtt-transport";

const protectedView = {
  schema_version: "vtt.table_view.v1",
  access_mode: "protected",
  table_id: "echo-vault-session",
  current_participant: {
    schema_version: "vtt.participant.v1",
    participant_id: "player-one",
    display_name: "Vela",
    role: "player",
    owned_actor_ids: ["vela"],
  },
  participants: [
    {
      schema_version: "vtt.participant.v1",
      participant_id: "gm",
      display_name: "Game Master",
      role: "gm",
      owned_actor_ids: [],
    },
    {
      schema_version: "vtt.participant.v1",
      participant_id: "player-one",
      display_name: "Vela",
      role: "player",
      owned_actor_ids: ["vela"],
    },
  ],
} as const;

test("strictly parses a token-free protected table directory", () => {
  assert.deepEqual(parseTableView(protectedView), protectedView);
  assert.throws(
    () => parseTableView({ ...protectedView, bearer_token: "must-never-leak" }),
    /unexpected field.*bearer_token/i,
  );
  assert.throws(
    () =>
      parseTableView({
        ...protectedView,
        current_participant: {
          ...protectedView.current_participant,
          participant_id: "missing",
        },
      }),
    /current participant.*directory/i,
  );
  assert.throws(
    () =>
      parseTableView({
        ...protectedView,
        participants: [...protectedView.participants].reverse(),
      }),
    /sorted.*participant/i,
  );
});

test("accepts only canonical bearer credentials and keeps them in headers", () => {
  const token = "table-token-1234567890";
  assert.equal(normalizeVttBearerToken(token), token);
  assert.equal(normalizeVttBearerToken(null), null);
  assert.throws(() => normalizeVttBearerToken("short"), /at least 16/i);
  assert.throws(
    () => normalizeVttBearerToken(` ${token}`),
    /whitespace/i,
  );
  assert.throws(
    () => normalizeVttBearerToken("table-token-é-123456"),
    /ASCII/i,
  );
  assert.deepEqual(
    buildVttRequestHeaders({
      accept: "text/event-stream",
      bearerToken: token,
    }),
    {
      accept: "text/event-stream",
      authorization: `Bearer ${token}`,
    },
  );
  assert.deepEqual(
    buildVttRequestHeaders({ accept: "application/json", bearerToken: null }),
    { accept: "application/json" },
  );
});

test("loads the table directory with bearer auth without placing secrets in URLs", async () => {
  const originalFetch = globalThis.fetch;
  const token = "table-token-1234567890";
  globalThis.fetch = (async (input, init) => {
    assert.equal(String(input), "http://127.0.0.1:8000/api/v1/table");
    assert.doesNotMatch(String(input), new RegExp(token));
    assert.deepEqual(init?.headers, {
      accept: "application/json",
      authorization: `Bearer ${token}`,
    });
    return Response.json(protectedView);
  }) as typeof fetch;
  try {
    assert.deepEqual(await getTableView({ bearerToken: token }), protectedView);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("derives ownership controls and valid private chat audiences from identity", () => {
  const table = parseTableView(protectedView);
  assert.equal(canControlActor(table.current_participant, "vela"), true);
  assert.equal(canControlActor(table.current_participant, "sentry"), false);
  assert.equal(
    canDeleteParticipantRecord(table.current_participant, "player-one"),
    true,
  );
  assert.equal(
    canDeleteParticipantRecord(table.current_participant, "gm"),
    false,
  );
  assert.deepEqual(chatAudienceChoices(table), [
    { key: "public", label: "Everyone", audience: ["all"] },
    { key: "gm", label: "Game Masters", audience: ["role:gm"] },
    {
      key: "participant:gm",
      label: "Direct · Game Master",
      audience: ["participant:gm"],
    },
  ]);

  const gm = table.participants[0];
  assert.equal(canControlActor(gm, "sentry"), true);
  assert.equal(canDeleteParticipantRecord(gm, "player-one"), true);
});
