import assert from "node:assert/strict";
import test from "node:test";
import { InstallationApi, parseJoinedWorldLaunch } from "../app/vtt-installation";
import { InvitationsApi, parseInvitation, parseInvitationIssued, parseWorldInvitations } from "../app/vtt-invitations";
import { parseSceneRefreshSseBlock, streamSceneEvents } from "../app/vtt-scenes";

const world = { schema_version: "vtt.world_record.v1", world_id: "world_one", table_id: "table_one", name: "Lantern Coast", system_id: "dnd5e" } as const;
const participant = { schema_version: "vtt.participant.v1", participant_id: "guest_one", display_name: "River", role: "player", owned_actor_ids: [] } as const;
const gm = { ...participant, participant_id: "gm_one", display_name: "Keeper", role: "gm" };
const launch = { schema_version: "vtt.world_launch.v1", world, session_id: "guest_session", workspace_api_path: "/api/v1/worlds/world_one", bearer_token: "guest_private_bearer_123456", table: { schema_version: "vtt.table_view.v1", table_id: world.table_id, access_mode: "protected", current_participant: participant, participants: [gm, participant] } };
const invitation = { invitation_id: "inv_one", role: "player", created_at: 100, expires_at: 86500, status: "pending", participant: null };

test("guest launch binds its world, table and local path without an administrator catalog", () => {
  assert.deepEqual(parseJoinedWorldLaunch(launch), launch);
  for (const invalid of [
    { ...launch, secret_extra: "leak" },
    { ...launch, table: { ...launch.table, table_id: "table_elsewhere" } },
    { ...launch, workspace_api_path: "https://elsewhere.test" },
    { ...launch, workspace_api_path: "/api/v1/worlds/world_one?token=leak" },
    ...["gm", "player"].map((role) => { const p = { ...participant, role, owned_actor_ids: role === "player" ? ["actor_one"] : [] }; return { ...launch, table: { ...launch.table, current_participant: p, participants: [p] } }; }),
    { ...launch, table: { ...launch.table, participants: [participant, { ...participant, participant_id: "guest_two" }] } },
  ]) assert.throws(() => parseJoinedWorldLaunch(invalid));
});

test("invitation codecs reject secrets, inconsistent state, duplicate IDs and foreign world binding", () => {
  assert.deepEqual(parseInvitation(invitation), invitation);
  const list = { schema_version: "vtt.world_invitations.v1", world_id: world.world_id, table_id: world.table_id, invitations: [invitation] };
  assert.deepEqual(parseWorldInvitations(list, world), list);
  for (const value of [{ ...invitation, token_hash: "secret" }, { ...invitation, role: "gm" }, { ...invitation, expires_at: 99 }, { ...invitation, status: "redeemed" }, { ...invitation, participant }, { ...invitation, created_at: 0.5 }]) assert.throws(() => parseInvitation(value));
  assert.throws(() => parseWorldInvitations({ ...list, world_id: "world_two" }, world));
  assert.throws(() => parseWorldInvitations({ ...list, invitations: [invitation, invitation] }, world));
  const issued = { schema_version: "vtt.invitation_issued.v1", invitation, replayed: false, invitation_token: "invitation_private_123456" };
  assert.deepEqual(parseInvitationIssued(issued, "player"), issued);
  assert.throws(() => parseInvitationIssued(issued, "spectator"));
  assert.throws(() => parseInvitationIssued({ ...issued, replayed: true }, "player"));
  assert.throws(() => parseInvitationIssued({ ...issued, invitation_token: null }, "player"));
  assert.equal(parseInvitationIssued({ ...issued, invitation_token: null, replayed: true }, "player").invitation_token, null);
});

test("join sends code only as a bearer and never echoes service error prose", async () => {
  const requests: { url: string; init: RequestInit }[] = [];
  const api = new InstallationApi("https://installation.test", async (url, init = {}) => { requests.push({ url: String(url), init }); return Response.json(launch); });
  await api.join("invite_private_token_123456", "River", new AbortController().signal);
  assert.equal(requests[0].url, "https://installation.test/api/v1/installation/join");
  assert.equal(requests[0].init.body, JSON.stringify({ display_name: "River" }));
  assert.equal(new Headers(requests[0].init.headers).get("authorization"), "Bearer invite_private_token_123456");
  assert.equal(requests[0].init.cache, "no-store");
  assert.equal(requests[0].init.credentials, "omit");
  assert.equal(requests[0].init.redirect, "error");
  const failed = new InstallationApi("https://installation.test", async () => Response.json({ schema_version: "vtt.error.v1", code: "invalid_invitation", message: "invite_private_token_123456", details: {} }, { status: 401 }));
  await assert.rejects(failed.join("invite_private_token_123456", "River", new AbortController().signal), (error: Error) => !error.message.includes("invite_private"));
});

test("invitation admin requests remain scoped, authenticated and secret-free in URLs", async () => {
  const calls: { url: string; init: RequestInit }[] = [];
  const api = new InvitationsApi("https://installation.test/api/v1/worlds/world_one", world, "world_private_bearer_123456", async (url, init = {}) => { calls.push({ url: String(url), init }); return new Response(null, { status: 204 }); });
  await api.revoke("inv_one", new AbortController().signal);
  assert.equal(calls[0].url, "https://installation.test/api/v1/worlds/world_one/api/v1/invitations/inv_one/revoke");
  assert.equal(calls[0].init.body, undefined);
  assert.equal(calls[0].init.method, "POST");
  assert.equal(new Headers(calls[0].init.headers).get("authorization"), "Bearer world_private_bearer_123456");
  await assert.rejects(api.revoke("../evil", new AbortController().signal));
  assert.equal(calls.length, 1);
});

test("guest scene streams accept only identity-free revision hints and require current projection reloads", async (context) => {
  assert.equal(parseSceneRefreshSseBlock('id: 3\nevent: vtt.scene_refresh\ndata: {"revision":3}'), 3);
  for (const block of [
    'id: 2\nevent: vtt.scene_refresh\ndata: {"revision":3}',
    'id: 03\nevent: vtt.scene_refresh\ndata: {"revision":3}',
    'id: 3\nevent: vtt.scene_refresh\ndata: {"revision":3,"scene_id":"secret"}',
    'id: 3\nevent: vtt.scene_event\ndata: {"revision":3}',
  ]) assert.throws(() => parseSceneRefreshSseBlock(block));
  const original = globalThis.fetch;
  context.after(() => { globalThis.fetch = original; });
  globalThis.fetch = async () => new Response('id: 3\nevent: vtt.scene_refresh\ndata: {"revision":3}\n\n', { headers: { "content-type": "text/event-stream" } });
  const refreshes: number[] = [];
  const cursor = await streamSceneEvents({ after: 0, signal: new AbortController().signal, onEvent() { assert.fail("guest stream must not emit historical events"); }, onRefresh(revision) { refreshes.push(revision); } });
  assert.equal(cursor, 3);
  assert.deepEqual(refreshes, [3]);
  await assert.rejects(streamSceneEvents({ after: 0, signal: new AbortController().signal, onEvent() {} }));
});
