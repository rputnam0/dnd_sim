import { parseTableView, type VttTableParticipant } from "./vtt-access";
import { InstallationApiError, type WorldRecord } from "./vtt-installation";
import { normalizeVttBearerToken } from "./vtt-transport";

export type InvitationRole = "player" | "spectator";
export interface Invitation {
  invitation_id: string;
  role: InvitationRole;
  created_at: number;
  expires_at: number;
  status: "pending" | "redeemed" | "revoked" | "expired";
  participant: VttTableParticipant | null;
}
export interface WorldInvitations {
  schema_version: "vtt.world_invitations.v1";
  world_id: string;
  table_id: string;
  invitations: Invitation[];
}
export interface InvitationIssued {
  schema_version: "vtt.invitation_issued.v1";
  invitation: Invitation;
  invitation_token: string | null;
  replayed: boolean;
}
function invalid(): never { throw new Error("The invitation service returned an invalid response."); }
function exact(value: unknown, keys: string[]): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) invalid();
  const data = value as Record<string, unknown>;
  if (Object.keys(data).length !== keys.length || keys.some((key) => !Object.hasOwn(data, key))) invalid();
  return data;
}
function id(value: unknown): string {
  if (typeof value !== "string" || !/^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/.test(value)) invalid();
  return value;
}
function timestamp(value: unknown): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0) invalid();
  return value;
}
function role(value: unknown): InvitationRole {
  if (value !== "player" && value !== "spectator") invalid();
  return value;
}
export function parseInvitation(value: unknown): Invitation {
  const data = exact(value, ["invitation_id", "role", "created_at", "expires_at", "status", "participant"]);
  const invitationRole = role(data.role);
  const created_at = timestamp(data.created_at);
  const expires_at = timestamp(data.expires_at);
  if (expires_at <= created_at || !["pending", "redeemed", "revoked", "expired"].includes(String(data.status))) invalid();
  let participant: VttTableParticipant | null = null;
  if (data.participant !== null) {
    participant = parseTableView({ schema_version: "vtt.table_view.v1", access_mode: "protected", table_id: "invitation", current_participant: data.participant, participants: [data.participant] }).current_participant;
    if (participant.role !== invitationRole || participant.owned_actor_ids.length !== 0 || !/^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/.test(participant.participant_id) ||
      [...participant.display_name].length > 80 || participant.display_name.normalize("NFKC") !== participant.display_name || /\p{C}/u.test(participant.display_name)) invalid();
  }
  if ((data.status === "redeemed" && participant === null) || (["pending", "expired"].includes(String(data.status)) && participant !== null)) invalid();
  return { invitation_id: id(data.invitation_id), role: invitationRole, created_at, expires_at, status: data.status as Invitation["status"], participant };
}
export function parseWorldInvitations(value: unknown, world: Pick<WorldRecord, "world_id" | "table_id">): WorldInvitations {
  const data = exact(value, ["schema_version", "world_id", "table_id", "invitations"]);
  if (data.schema_version !== "vtt.world_invitations.v1" || data.world_id !== world.world_id || data.table_id !== world.table_id || !Array.isArray(data.invitations)) invalid();
  const invitations = data.invitations.map(parseInvitation);
  if (new Set(invitations.map((entry) => entry.invitation_id)).size !== invitations.length) invalid();
  return { schema_version: "vtt.world_invitations.v1", world_id: id(data.world_id), table_id: id(data.table_id), invitations };
}
export function parseInvitationIssued(value: unknown, expectedRole: InvitationRole): InvitationIssued {
  const data = exact(value, ["schema_version", "invitation", "invitation_token", "replayed"]);
  const invitation = parseInvitation(data.invitation);
  if (data.schema_version !== "vtt.invitation_issued.v1" || typeof data.replayed !== "boolean" || invitation.role !== expectedRole) invalid();
  if (data.replayed ? data.invitation_token !== null : typeof data.invitation_token !== "string" || !/^[A-Za-z0-9_-]{16,256}$/.test(data.invitation_token) || invitation.status !== "pending") invalid();
  return { schema_version: "vtt.invitation_issued.v1", invitation, replayed: data.replayed, invitation_token: data.invitation_token as string | null };
}

/** This transport has no storage, URL credentials, or server-prose error paths. */
export class InvitationsApi {
  private readonly base: string;
  constructor(base: string, private readonly world: Pick<WorldRecord, "world_id" | "table_id">, private readonly token: string, private readonly fetcher: typeof fetch = (...args) => fetch(...args)) {
    const url = new URL(base);
    if (!["https:", "http:"].includes(url.protocol) || url.username || url.password || url.search || url.hash || !url.pathname.endsWith(`/api/v1/worlds/${id(world.world_id)}`)) invalid();
    id(world.table_id);
    normalizeVttBearerToken(token);
    this.base = base.replace(/\/+$/, "");
  }
  private async request<T>(path: string, signal: AbortSignal, parser: ((value: unknown) => T) | null, method = "GET", body?: unknown, status = 200): Promise<T> {
    let response: Response;
    try {
      response = await this.fetcher(`${this.base}/api/v1/invitations${path}`, {
        method, headers: { Accept: "application/json", Authorization: `Bearer ${this.token}`, ...(body === undefined ? {} : { "Content-Type": "application/json" }) },
        ...(body === undefined ? {} : { body: JSON.stringify(body) }), signal, cache: "no-store", credentials: "omit", redirect: "error",
      });
    } catch (error) {
      if (signal.aborted) throw error;
      throw new InstallationApiError(null, "connection_unavailable", "The invitation service could not be reached. Refresh the list to check whether your change completed.");
    }
    if (!response.ok) throw new InstallationApiError(response.status, "invitation_request_failed", response.status === 409 ? "The invitation limit or command conflicts with this request. Refresh the list and revoke unused access before trying again." : "The invitation request was not accepted. Refresh the list or sign in again.");
    if (response.status !== status) throw new InstallationApiError(null, "invalid_response", "The invitation response could not be verified. Refresh the list to check its state.");
    if (!parser) return undefined as T;
    try { return parser(await response.json()); }
    catch { throw new InstallationApiError(null, "invalid_response", "The invitation response could not be verified. Refresh the list to check its state."); }
  }
  list(signal: AbortSignal) { return this.request("", signal, (value) => parseWorldInvitations(value, this.world)); }
  issue(commandId: string, invitationRole: InvitationRole, signal: AbortSignal) {
    return this.request("", signal, (value) => parseInvitationIssued(value, invitationRole), "POST", { command_id: id(commandId), role: role(invitationRole) }, 201);
  }
  async revoke(invitationId: string, signal: AbortSignal) { await this.request<void>(`/${id(invitationId)}/revoke`, signal, null, "POST", undefined, 204); }
}
