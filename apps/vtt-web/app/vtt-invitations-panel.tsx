"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { InstallationApiError, type WorldLaunch } from "./vtt-installation";
import { InvitationsApi, type Invitation, type InvitationRole } from "./vtt-invitations";

type Props = { launch: WorldLaunch; apiBaseUrl: string; onAccessLost: () => void; copyCode?: (code: string) => Promise<void> };

export function VttInvitationsPanel(props: Props) {
  if (props.launch.table.current_participant.role !== "gm") return null;
  return <InvitationManager key={`${props.apiBaseUrl}:${props.launch.session_id}`} {...props} />;
}

function InvitationManager({ launch, apiBaseUrl, onAccessLost, copyCode }: Props) {
  const api = useMemo(() => new InvitationsApi(apiBaseUrl, launch.world, launch.bearer_token), [apiBaseUrl, launch]);
  const [invitations, setInvitations] = useState<Invitation[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [secret, setSecret] = useState<{ id: string; token: string } | null>(null);
  const [revoking, setRevoking] = useState<Invitation | null>(null);
  const [retry, setRetry] = useState<{ id: string; role: InvitationRole } | null>(null);
  const active = useRef<AbortController | null>(null);
  const mounted = useRef(true);
  const accessLost = useRef(onAccessLost);
  useEffect(() => { accessLost.current = onAccessLost; }, [onAccessLost]);
  const begin = () => { active.current?.abort(); const controller = new AbortController(); active.current = controller; setBusy(true); return controller; };
  const current = (controller: AbortController) => mounted.current && active.current === controller && !controller.signal.aborted;
  const failure = (error: unknown) => {
    if (error instanceof InstallationApiError && [401, 403, 404, 410].includes(error.status ?? 0)) { setSecret(null); accessLost.current(); }
    else setNotice(error instanceof InstallationApiError ? error.message : "The invitation change could not be verified. Refresh the list before issuing another code.");
  };
  const refresh = async () => {
    const controller = begin();
    try {
      const result = await api.list(controller.signal);
      if (!current(controller)) return;
      setInvitations(result.invitations);
      setSecret((saved) => saved && result.invitations.some((entry) => entry.invitation_id === saved.id && entry.status === "pending") ? saved : null);
    } catch (error) { if (current(controller)) failure(error); }
    finally { if (current(controller)) setBusy(false); }
  };
  useEffect(() => {
    mounted.current = true;
    const controller = new AbortController(); active.current = controller;
    void api.list(controller.signal).then((result) => { if (!controller.signal.aborted) setInvitations(result.invitations); }).catch((error: unknown) => {
      if (controller.signal.aborted) return;
      if (error instanceof InstallationApiError && [401, 403, 404, 410].includes(error.status ?? 0)) accessLost.current();
      else setNotice("Invitations could not be loaded. Refresh the list to try again.");
    });
    return () => { mounted.current = false; active.current?.abort(); };
  }, [api]);
  const issue = async (role: InvitationRole, commandId = `invite_${crypto.randomUUID().replaceAll("-", "")}`) => {
    if (busy) return;
    const controller = begin(); setNotice(null); setSecret(null); setRetry({ id: commandId, role });
    try {
      const result = await api.issue(commandId, role, controller.signal);
      if (!current(controller)) return;
      setRetry(null);
      setInvitations((records) => [...(records ?? []).filter((entry) => entry.invitation_id !== result.invitation.invitation_id), result.invitation]);
      setSecret(result.invitation_token ? { id: result.invitation.invitation_id, token: result.invitation_token } : null);
      setNotice(result.invitation_token ? "Invitation created. Copy the code now and share it privately with one guest. It expires in 24 hours." : "This invitation was already created. Its code cannot be recovered. Refresh the list, revoke it, and create a replacement if the code was lost.");
    } catch (error) { if (current(controller)) failure(error); }
    finally { if (current(controller)) setBusy(false); }
  };
  const revoke = async () => {
    if (!revoking || busy) return;
    const controller = begin(); const target = revoking;
    try {
      await api.revoke(target.invitation_id, controller.signal);
      if (!current(controller)) return;
      setInvitations((records) => records?.map((entry) => entry.invitation_id === target.invitation_id ? { ...entry, status: "revoked" } : entry) ?? null);
      setSecret((saved) => saved?.id === target.invitation_id ? null : saved);
      setRevoking(null); setNotice("Access revoked. The code and any linked guest sessions no longer work.");
    } catch (error) { if (current(controller)) failure(error); }
    finally { if (current(controller)) setBusy(false); }
  };
  const copy = async () => {
    if (!secret) return;
    const token = secret.token; const controller = active.current;
    try {
      await (copyCode ? copyCode(token) : navigator.clipboard.writeText(token));
      if (mounted.current && controller === active.current) setNotice("Invitation code copied. Share it privately, then clear it from your clipboard when finished.");
    } catch {
      if (mounted.current && controller === active.current) setNotice("Clipboard access failed. Retry copying, or revoke this invitation and create a replacement. The code is kept only until this workspace closes.");
    }
  };
  return <section className="vw-invitations" aria-label="Participant invitations">
    <div className="vw-invitation-heading"><div><p className="vi-eyebrow">BRING YOUR TABLE TOGETHER</p><h2>Participant invitations</h2></div><button className="vi-button vi-secondary" onClick={refresh} disabled={busy}>Refresh invitations</button></div>
    <p>Invite a player or spectator to view published scenes. Up to ten active guests. Codes are single-use and expire after 24 hours; guest sessions end after four hours, a reload, or a service restart. Actors and combat are not available here.</p>
    <div className="vi-inline-actions"><button className="vi-button vi-primary" disabled={busy} onClick={() => issue("player")}>Create player invitation</button><button className="vi-button vi-secondary" disabled={busy} onClick={() => issue("spectator")}>Create spectator invitation</button></div>
    <p>Send your guest to <a href="/join" target="_blank" rel="noreferrer">the join page</a> and share their code separately. No code is included in the link.</p>
    {notice && <p className="vi-notice" role="status">{notice}</p>}
    {secret && <div className="vw-invitation-secret"><p>The code is held only in this workspace. Refreshing the page loses it.</p><button className="vi-button vi-primary" onClick={copy}>Copy invitation code</button></div>}
    {retry && <div className="vw-invitation-secret"><p>A create response was lost. Check the list before retrying; an exact retry cannot reveal a lost code.</p><button className="vi-button vi-secondary" disabled={busy} onClick={() => issue(retry.role, retry.id)}>Retry original invitation</button></div>}
    {invitations === null ? <p>Loading invitation records…</p> : invitations.length === 0 ? <p>No invitations yet. Start with the role your guest needs.</p> : <ul className="vw-invitation-list">{invitations.map((entry) => <li key={entry.invitation_id}><div><strong>{entry.participant?.display_name ?? `${entry.role === "player" ? "Player" : "Spectator"} invitation`}</strong><span>{entry.role} · {entry.status}</span><span>{entry.status === "pending" ? "Code expires" : "Code expiry"}: {new Date(entry.expires_at * 1_000).toLocaleString()}</span></div>{["pending", "redeemed"].includes(entry.status) && <button className="vi-button vi-secondary vi-danger-text" disabled={busy} onClick={() => setRevoking(entry)}>Revoke invitation</button>}</li>)}</ul>}
    {revoking && <section className="vw-invitation-confirm" aria-label="Confirm invitation revocation"><h3>End this access?</h3><p>This immediately invalidates the invitation and all linked guest sessions. Your world’s scenes and maps are not deleted.</p><div className="vi-inline-actions"><button className="vi-button vi-danger" disabled={busy} onClick={revoke}>Confirm revoke</button><button className="vi-button vi-secondary" disabled={busy} onClick={() => setRevoking(null)}>Keep access</button></div></section>}
  </section>;
}
