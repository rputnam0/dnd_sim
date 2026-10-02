"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { InstallationApi, type WorldLaunch } from "./vtt-installation";
import { VttGuestWorkspace } from "./vtt-guest-workspace";

export function VttJoinGate({ apiBaseUrl }: { apiBaseUrl?: string }) { return <JoinSession key={apiBaseUrl ?? "default"} apiBaseUrl={apiBaseUrl} />; }

function JoinSession({ apiBaseUrl }: { apiBaseUrl?: string }) {
  const api = useMemo(() => { try { return new InstallationApi(apiBaseUrl); } catch { return null; } }, [apiBaseUrl]);
  const [code, setCode] = useState(""); const [name, setName] = useState("");
  const [launch, setLaunch] = useState<WorldLaunch | null>(null);
  const [busy, setBusy] = useState(false); const [notice, setNotice] = useState<string | null>(null);
  const active = useRef<AbortController | null>(null);
  const generation = useRef(0);
  const heading = useRef<HTMLHeadingElement>(null);
  const invalidate = useCallback(() => { generation.current += 1; active.current?.abort(); active.current = null; }, []);
  useEffect(() => () => { invalidate(); }, [invalidate]);
  useEffect(() => { if (!launch) heading.current?.focus(); }, [launch]);
  const end = useCallback((message: string) => {
    invalidate(); setLaunch(null); setCode(""); setName(""); setBusy(false); setNotice(message);
  }, [invalidate]);
  const accessLost = useCallback(() => end("Access to this world ended or could not be verified. Ask your Game Master for a new invitation."), [end]);
  const join = async (event: FormEvent) => {
    event.preventDefault(); if (busy || !api) return;
    if (!/^[A-Za-z0-9_-]{16,256}$/.test(code) || name !== name.trim() || [...name].length < 1 || [...name].length > 80 || name.normalize("NFKC") !== name || /\p{C}/u.test(name)) {
      setNotice("Enter a valid invitation code and a display name of 1–80 characters without surrounding spaces."); return;
    }
    invalidate(); const requestGeneration = generation.current; const controller = new AbortController(); active.current = controller;
    const submitted = code; setCode(""); setBusy(true); setNotice(null);
    const current = () => generation.current === requestGeneration && !controller.signal.aborted;
    try {
      const result = await api.join(submitted, name, controller.signal);
      if (!current()) return;
      setName(""); setLaunch(result);
    } catch {
      if (current()) setNotice("The invitation could not be redeemed. Codes expire and can be used only once. If a response was lost, ask your Game Master to revoke that access and send a new invitation.");
    } finally { if (current()) setBusy(false); }
  };
  const leave = () => {
    const previous = launch;
    end("You left the world. Ask your Game Master for a new invitation to join again.");
    if (previous && api) {
      const controller = new AbortController(); active.current = controller;
      // The private view is already unmounted. A late return never changes a new join.
      void api.returnWorld(previous.world.world_id, previous.bearer_token, controller.signal).catch(() => {});
    }
  };
  return <div className="vi-app"><header className="vi-topbar"><a className="vi-brand" href="/join" aria-label="DND Sim guest home"><span className="vi-brand-mark" aria-hidden="true">◇</span><span>DND Sim<small>JOIN A WORLD</small></span></a><nav className="vi-topnav"><a className="vi-demo-link" href="/setup">Game Master sign in</a></nav></header><main className="vi-main">
    {launch && api ? <VttGuestWorkspace key={launch.session_id} launch={launch} apiBaseUrl={api.workspaceBaseUrl(launch)} onLeave={leave} onAccessLost={accessLost} /> : <div className="vi-welcome-grid"><section className="vi-introduction"><p className="vi-eyebrow">YOUR PLACE AT THE TABLE</p><h1 ref={heading} tabIndex={-1}>Every story starts<br />with an invitation.</h1><p className="vi-lede">Join your Game Master’s world to see its published scene. Bring the code they shared with you and the name you use at the table.</p><p className="vi-lede">Player and spectator invitations open a read-only map view. Actors, tokens, and combat are not available in this workspace.</p></section><section className="vi-auth-card vj-auth"><h2>Join a world</h2><p>One invitation. One guest. No account required.</p>{notice && <p className="vi-notice" role="status">{notice}</p>}{!api && <p role="alert">The installation address is unavailable. Ask your Game Master to check the service.</p>}<form className="vi-form" aria-label="Join a world" onSubmit={join} autoComplete="off"><label htmlFor="invitation-code">Invitation code<input id="invitation-code" name="invitation-code" type="password" autoComplete="off" spellCheck={false} autoCapitalize="none" value={code} disabled={busy} onChange={(event) => setCode(event.target.value)} required maxLength={256} /></label><label htmlFor="guest-display-name">Display name<input id="guest-display-name" name="display-name" autoComplete="off" value={name} disabled={busy} onChange={(event) => setName(event.target.value)} required maxLength={80} /></label><button className="vi-button vi-primary" type="submit" disabled={busy || !api}>{busy ? "Joining…" : "Join world"}<span aria-hidden="true">→</span></button>{busy && <button className="vi-button vi-secondary" type="button" onClick={() => end("Joining cancelled. The code may already have been used. Ask your Game Master for a new invitation if needed.")}>Cancel joining</button>}</form><p className="vi-security-note">Codes expire after 24 hours. Access is held only in this page’s memory; a reload or service restart requires another invitation. Never put the code in a URL.</p></section></div>}
  </main><footer className="vi-footer"><span>Private worlds. Shared imagination.</span><span>Local installation · Invitation-only access</span></footer></div>;
}
