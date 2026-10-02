"use client";

import { useEffect, useRef, useState } from "react";
import AdventureMap from "./adventure-map";
import { buildAdventureChoice, getAdventureView, postAdventureCommand, type AdventureView } from "./adventure-client";
import { buildDeclarationCommand, planGridMovement, VttApiError, type GridCell, type GridMovementPlan, type VttCommand } from "./vtt-client";

type Connection = "loading" | "ready" | "saving" | "uncertain" | "error";
function message(error: unknown) { return error instanceof Error ? error.message : "The adventure could not connect."; }

export default function AdventurePlay() {
  const [view, setView] = useState<AdventureView | null>(null);
  const [status, setStatus] = useState<Connection>("loading");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const inFlight = useRef(false);
  const uncertain = useRef<VttCommand | null>(null);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    const abort = new AbortController();
    getAdventureView(AbortSignal.any([abort.signal, AbortSignal.timeout(20_000)])).then((loaded) => {
      if (mounted.current) { setView(loaded); setStatus("ready"); }
    }).catch((failure) => {
      if (!abort.signal.aborted && mounted.current) { setError(message(failure)); setStatus("error"); }
    });
    return () => { mounted.current = false; abort.abort(); };
  }, []);

  async function reload() {
    if (inFlight.current || uncertain.current) return;
    inFlight.current = true; setStatus("loading"); setError(null);
    try {
      const loaded = await getAdventureView(AbortSignal.timeout(20_000));
      if (mounted.current) { setView(loaded); setStatus("ready"); }
    } catch (failure) {
      if (mounted.current) { setError(message(failure)); setStatus("error"); }
    } finally { inFlight.current = false; }
  }

  async function submit(command: VttCommand, retry = false) {
    if (inFlight.current || (uncertain.current && !retry)) return;
    inFlight.current = true; uncertain.current = command;
    setStatus("saving"); setError(null); setNotice(null);
    let confirmed = false;
    try {
      await postAdventureCommand(command);
      confirmed = true; uncertain.current = null;
      const loaded = await getAdventureView(AbortSignal.timeout(20_000));
      if (mounted.current) { setView(loaded); setStatus("ready"); }
    } catch (failure) {
      if (!mounted.current) return;
      const rejected = failure instanceof VttApiError && failure.status >= 400 && failure.status < 500;
      if (rejected) {
        uncertain.current = null;
        setNotice(failure.status === 409 ? "The adventure changed. Your view has been refreshed; choose your next action." : message(failure));
        try {
          const loaded = await getAdventureView(AbortSignal.timeout(20_000));
          if (mounted.current) { setView(loaded); setStatus("ready"); }
        } catch (loadFailure) {
          if (mounted.current) { setError(message(loadFailure)); setStatus("error"); }
        }
      } else {
        setError(confirmed ? `Your action was saved. Reconnect to see the result. ${message(failure)}` : `${message(failure)} The result is not yet confirmed. Retry the saved action to recover it safely.`);
        setStatus(confirmed ? "error" : "uncertain");
      }
    } finally { inFlight.current = false; }
  }

  const locked = status !== "ready";
  return <main className="adventure-shell">
    <a className="skip-link" href="#adventure-story">Skip to adventure choices</a>
    {view?.phase === "combat" ? <a className="skip-link" href="#adventure-combat">Skip to turn controls</a> : null}
    <header className="adventure-header">
      <div><p className="eyebrow">A DND Sim adventure · One player, three companions</p>
        <h1>{view?.title ?? "The Lantern Below"}</h1>
        <p>{view?.subtitle ?? "A light is fading beneath the harbor."}</p></div>
      <div className="adventure-save"><span role="status" aria-live="polite">{
        status === "ready" ? "Progress saved automatically" : status === "saving" ? "Resolving your action…" :
        status === "loading" ? "Loading saved adventure…" : status === "uncertain" ? "Waiting to confirm save" : "Connection interrupted"
      }</span><button type="button" disabled={status === "saving" || status === "loading" || status === "uncertain"} onClick={() => void reload()}>Reload adventure</button></div>
    </header>
    {error ? <div className="adventure-message adventure-error" role="alert"><p>{error}</p>
      {status === "uncertain" ? <button type="button" onClick={() => { if (uncertain.current) void submit(uncertain.current, true); }}>Retry saved action</button>
        : <button type="button" disabled={status === "loading" || status === "saving"} onClick={() => void reload()}>Reconnect</button>}
    </div> : null}
    {notice ? <p className="adventure-message" role="status">{notice}</p> : null}
    {view ? <AdventureBoard key={`${view.session_id}:${view.revision}`} view={view} locked={locked} onCommand={(command) => void submit(command)} />
      : <section className="adventure-panel"><h2>Gathering the party</h2><p>Your most recent adventure will resume here.</p></section>}
  </main>;
}

function AdventureBoard({ view, locked, onCommand }: { view: AdventureView; locked: boolean; onCommand: (command: VttCommand) => void }) {
  const combat = view.phase === "combat" ? view.combat : null;
  const active = combat?.active_actor_id ? combat.actors[combat.active_actor_id] : null;
  const actions = combat?.choices?.actions.filter((action) => action.action_cost !== "bonus") ?? [];
  const bonusActions = combat?.choices?.actions.filter((action) => action.action_cost === "bonus") ?? [];
  const [actionName, setActionName] = useState(actions[0]?.action_name ?? "");
  const [bonusName, setBonusName] = useState("");
  const [bonusTargetId, setBonusTargetId] = useState<string | null>(null);
  const [targetId, setTargetId] = useState<string | null>(null);
  const [movement, setMovement] = useState<GridMovementPlan | null>(null);
  const [selectedActorId, setSelectedActorId] = useState(active?.actor_id ?? view.party[0]?.actor_id ?? "");
  const [confirmRestart, setConfirmRestart] = useState(false);
  const action = actions.find((entry) => entry.action_name === actionName);
  const bonusAction = bonusActions.find((entry) => entry.action_name === bonusName);
  const lastExchange = [...view.journal].reverse().find((entry) => entry.id.startsWith("combat_"));
  const targetIds = new Set(action?.selectable_target_ids ?? []);
  const reachable = new Set<string>();
  if (active && !locked) {
    for (let row = 0; row < view.scene.rows; row++) for (let column = 0; column < view.scene.columns; column++) {
      try {
        planGridMovement({ scene: view.scene, start: active.position, destination: { column, row }, movementRemaining: active.movement_remaining });
        reachable.add(`${column}:${row}`);
      } catch { /* The remaining movement does not reach this square. */ }
    }
  }
  function selectCell(destination: GridCell) {
    if (!active || locked || !reachable.has(`${destination.column}:${destination.row}`)) return;
    setMovement(planGridMovement({ scene: view.scene, start: active.position, destination, movementRemaining: active.movement_remaining }));
  }
  const canTakeTurn = !locked && active?.team === "party" && action &&
    (!action.requires_explicit_targets || (targetId !== null && targetIds.has(targetId))) &&
    (!bonusAction?.requires_explicit_targets || (bonusTargetId !== null && bonusAction.selectable_target_ids.includes(bonusTargetId)));
  const selected = (combat?.actors ?? Object.fromEntries(view.party.map((actor) => [actor.actor_id, actor])))[selectedActorId];

  return <>
    <section className="adventure-objective" aria-label="Current objective"><span className="eyebrow">Current objective</span><strong>{view.objective}</strong><span className="adventure-phase">{view.phase === "combat" ? `Combat · round ${combat?.round_number}` : view.phase}</span></section>
    <div className="adventure-layout">
      <div className="adventure-center">
        <AdventureMap view={view} selectedActorId={selectedActorId} targets={locked ? new Set() : targetIds} targetId={targetId}
          reachable={reachable} movement={movement} onActor={setSelectedActorId}
          onTarget={(id) => { if (!locked) setTargetId(id); }} onCell={selectCell} />
        {combat && active ? <section className="adventure-panel adventure-combat" id="adventure-combat" aria-labelledby="adventure-turn-title">
          <p className="eyebrow">Your party’s turn</p><h2 id="adventure-turn-title">{active.name}’s turn</h2>
          {lastExchange ? <div className="adventure-recap" aria-label="Last exchange" aria-live="polite"><strong>Last exchange</strong><p>{lastExchange.text}</p></div> : null}
          <p>Choose movement on the map, then an action and target. Movement happens first. Enemies and reactions resolve automatically.</p>
          <fieldset disabled={locked}><legend className="sr-only">Plan your turn</legend>
            <label>Action<select aria-label="Action" value={actionName} onChange={(event) => { setActionName(event.target.value); setTargetId(null); }}>
              {actions.map((entry) => <option key={entry.action_name} value={entry.action_name}>{entry.action_name}</option>)}
            </select></label>
            {action?.requires_explicit_targets ? <label>Target<select aria-label="Target" value={targetId ?? ""} onChange={(event) => setTargetId(event.target.value || null)}>
              <option value="">Choose a target</option>{[...targetIds].map((id) => <option key={id} value={id}>{combat.actors[id].name}{action.legal_target_ids.includes(id) ? "" : " · move into range"}</option>)}
            </select></label> : null}
            {bonusActions.length ? <label>Bonus action<select aria-label="Bonus action" value={bonusName} onChange={(event) => { setBonusName(event.target.value); setBonusTargetId(null); }}>
              <option value="">None</option>{bonusActions.map((entry) => <option key={entry.action_name} value={entry.action_name}>{entry.action_name}</option>)}
            </select></label> : null}
            {bonusAction?.requires_explicit_targets ? <label>Bonus target<select aria-label="Bonus target" value={bonusTargetId ?? ""} onChange={(event) => setBonusTargetId(event.target.value || null)}>
              <option value="">Choose a target</option>{bonusAction.selectable_target_ids.map((id) => <option key={id} value={id}>{combat.actors[id].name}{bonusAction.legal_target_ids.includes(id) ? "" : " · move into range"}</option>)}
            </select></label> : null}
            <div className="adventure-move"><span>{movement ? `Move ${movement.distanceFt} ft to ${String.fromCharCode(65 + movement.destination.row)}${movement.destination.column + 1}` : `Stay in place · ${active.movement_remaining} ft available`}</span>
              <button type="button" disabled={!movement} onClick={() => setMovement(null)}>Clear movement</button></div>
            <button className="adventure-primary" type="button" disabled={!canTakeTurn} onClick={() => {
              if (!canTakeTurn || !active || !action) return;
              const command = buildDeclarationCommand({ sessionId: view.session_id, expectedRevision: view.revision,
                actorId: active.actor_id, actionName, targetIds: action.requires_explicit_targets && targetId ? [targetId] : [],
                movementPath: movement?.path ?? [], mode: "commit" });
              if (bonusAction) {
                command.payload.bonus_action = { action_name: bonusAction.action_name,
                  targets: bonusAction.requires_explicit_targets && bonusTargetId ? [{ actor_id: bonusTargetId }] : [],
                  resource_spend: { amounts: {} }, spell_slot_level: null, rationale: {} };
              }
              onCommand(command);
            }}>Take turn</button>
          </fieldset>
          {action?.requires_explicit_targets && targetIds.size === 0 ? <p>No targets are available for this action. Choose another action.</p> : null}
        </section> : null}
        <section className="adventure-panel adventure-story" id="adventure-story" aria-labelledby="adventure-location-title">
          <p className="eyebrow">{view.phase === "complete" ? "Adventure complete" : view.phase === "defeat" ? "The party has fallen" : "The journey"}</p>
          <h2 id="adventure-location-title">{view.location.name}</h2><p>{view.location.description}</p>
          {view.dialogue ? <blockquote><p>{view.dialogue.text}</p><footer>— {view.dialogue.speaker}</footer></blockquote> : null}
          {view.ending ? <div className="adventure-ending" role="status"><h3>{view.ending.title}</h3><p>{view.ending.text}</p></div> : null}
          <div className="adventure-choices" aria-label="Adventure choices">{view.choices.map((choice) => <button type="button" disabled={locked} key={choice.id} onClick={() => {
            if (locked) return;
            if (choice.id === "restart") setConfirmRestart(true);
            else onCommand(buildAdventureChoice(view, choice.id));
          }}><strong>{choice.label}</strong><span>{choice.description}</span><span aria-hidden="true" className="adventure-choice-arrow">↗</span></button>)}</div>
          {confirmRestart ? <div className="adventure-confirm" role="alertdialog" aria-modal="false" aria-labelledby="adventure-restart-title" aria-describedby="adventure-restart-description">
            <h3 id="adventure-restart-title">Begin a new adventure?</h3><p id="adventure-restart-description">This replaces your current playthrough with a fresh party and new choices.</p>
            <button type="button" autoFocus disabled={locked} onClick={() => setConfirmRestart(false)}>Keep this adventure</button>
            <button type="button" disabled={locked} onClick={() => { if (!locked) onCommand(buildAdventureChoice(view, "restart")); }}>Start new adventure</button>
          </div> : null}
        </section>
      </div>
      <aside className="adventure-sidebar" aria-label="Adventure companions and records">
        <section className="adventure-panel"><p className="eyebrow">Together below the tide</p><h2>Your party</h2>
          <div className="adventure-party">{view.party.map((actor) => <button type="button" key={actor.actor_id} aria-pressed={selectedActorId === actor.actor_id} onClick={() => setSelectedActorId(actor.actor_id)}>
            <span className="portrait-token team-party">{actor.name.slice(0, 1)}</span><span><strong>{actor.name}</strong><span>{actor.hp} / {actor.max_hp} HP · AC {actor.ac}</span><meter min={0} max={actor.max_hp} value={actor.hp} aria-label={`${actor.name} hit points`} /></span>
          </button>)}</div>
          {selected ? <p className="adventure-inspector"><strong>{selected.name}</strong> · {selected.hp} / {selected.max_hp} HP{selected.dead ? " · Fallen" : ""}{selected.conditions.length ? ` · ${selected.conditions.join(", ")}` : " · No conditions"}</p> : null}
        </section>
        <section className="adventure-panel"><p className="eyebrow">Shared supplies</p><h2>Inventory</h2>
          {view.inventory.length ? <ul className="adventure-items">{view.inventory.map((item) => <li key={item.id}><strong>{item.name}<span> × {item.quantity}</span></strong><p>{item.description}</p></li>)}</ul> : <p>Your packs are light. Search for supplies along the way.</p>}
        </section>
        <section className="adventure-panel"><p className="eyebrow">Your story so far</p><h2>Journal</h2>
          {view.journal.length ? <ol className="adventure-journal">{[...view.journal].reverse().map((entry) => <li key={entry.id}><h3>{entry.title}</h3><p>{entry.text}</p></li>)}</ol> : <p>The first page is waiting.</p>}
        </section>
        <details className="adventure-panel adventure-help"><summary>How to play</summary><p>Choose the story actions below the map to explore, talk, search and rest. During combat you control each companion when their turn arrives.</p><p>Select a highlighted map square to move. Choose an action and target, then take your turn. You can use Tab and Enter for every control. Progress saves after each action; reload to resume.</p></details>
      </aside>
    </div>
  </>;
}
