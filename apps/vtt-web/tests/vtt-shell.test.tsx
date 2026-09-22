import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { createElement, useEffect } from "react";
import TestRenderer, { act } from "react-test-renderer";

import { VttShell, type VttShellPanel } from "../app/vtt-shell";
import type { VttWorkspacePreferenceStorage } from "../app/vtt-workspace-state";

const reactTestEnvironment: typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean } = globalThis;
reactTestEnvironment.IS_REACT_ACT_ENVIRONMENT = true;

const panels: VttShellPanel[] = [
  { id: "combat", label: "Combat", modes: ["play"], content: "Combat surface" },
  { id: "activity", label: "Activity", modes: ["play"], content: "Activity surface" },
  { id: "chat", label: "Chat", modes: ["play"], content: "Chat surface" },
  { id: "journal", label: "Journal", modes: ["play", "prepare"], content: "Journal surface" },
  { id: "participants", label: "Participants", modes: ["play"], content: "Participant surface" },
  { id: "events", label: "Events", modes: ["play"], content: "Event surface" },
  { id: "scenes", label: "Scenes", modes: ["prepare"], roles: ["gm"], content: "Scene surface" },
  { id: "tokens", label: "Tokens", modes: ["prepare"], roles: ["gm"], content: "Token surface" },
  { id: "visibility", label: "Visibility", modes: ["prepare"], roles: ["gm"], content: "Visibility surface" },
  { id: "sound", label: "Sound", modes: ["prepare"], roles: ["gm"], content: "Sound surface" },
  { id: "gm-events", label: "GM events", modes: ["play"], roles: ["gm"], content: "GM event surface" },
];

function findButton(
  root: TestRenderer.ReactTestInstance,
  name: string,
): TestRenderer.ReactTestInstance {
  const button = root
    .findAllByType("button")
    .find((candidate) => candidate.children.join("") === name);
  assert.ok(button, `Expected a ${name} button`);
  return button;
}

test("GM switches Play, Prepare, and panel tabs without remounting the map", async () => {
  let mapMounts = 0;
  let mapUnmounts = 0;
  const writes: string[] = [];
  const storage: VttWorkspacePreferenceStorage = {
    read: () => null,
    write: (value) => writes.push(value),
  };
  function MapProbe() {
    useEffect(() => {
      mapMounts += 1;
      return () => {
        mapUnmounts += 1;
      };
    }, []);
    return createElement("div", null, "Persistent tactical map");
  }

  let renderer: TestRenderer.ReactTestRenderer;
  await act(async () => {
    renderer = TestRenderer.create(
      createElement(VttShell, {
        role: "gm",
        worldName: "Northwatch",
        sceneName: "Sable Vault",
        connectionLabel: "Live",
        mapSlot: createElement(MapProbe),
        actionSlot: createElement("div", null, "Command actions"),
        initiativeSlot: createElement("div", null, "Initiative order"),
        panels,
        preferenceStorage: storage,
      }),
    );
  });

  const root = renderer!.root;
  assert.equal(mapMounts, 1);
  assert.equal(mapUnmounts, 0);
  assert.deepEqual(
    root.findAllByProps({ role: "tab" }).map((tab) => tab.children.join("")),
    ["Combat", "Activity", "Chat", "Journal", "Participants", "Events", "GM events"],
  );

  await act(async () => findButton(root, "Prepare").props.onClick());
  assert.deepEqual(
    root.findAllByProps({ role: "tab" }).map((tab) => tab.children.join("")),
    ["Journal", "Scenes", "Tokens", "Visibility", "Sound"],
  );
  await act(async () => findButton(root, "Tokens").props.onClick());
  assert.match(JSON.stringify(renderer!.toJSON()), /Token surface/);
  await act(async () => findButton(root, "Play").props.onClick());
  await act(async () => findButton(root, "Chat").props.onClick());

  assert.equal(mapMounts, 1);
  assert.equal(mapUnmounts, 0);
  assert.equal(root.findByProps({ id: "vtt-map" }).children.length, 1);
  assert.equal(root.findByProps({ id: "vtt-actions" }).children.length, 1);
  assert.equal(root.findByProps({ id: "vtt-initiative" }).children.length, 1);
  assert.equal(writes.at(-1), '{"mode":"play","panel_id":"chat"}');

  await act(async () => renderer!.unmount());
  assert.equal(mapUnmounts, 1);
});

test("player and spectator shells expose Play without Prepare or GM panels", async () => {
  for (const role of ["player", "spectator"] as const) {
    let renderer: TestRenderer.ReactTestRenderer;
    await act(async () => {
      renderer = TestRenderer.create(
        createElement(VttShell, {
          role,
          worldName: "Northwatch",
          sceneName: "Sable Vault",
          connectionLabel: "Live",
          mapSlot: "Map",
          actionSlot: "Actions",
          initiativeSlot: "Initiative",
          panels,
        }),
      );
    });
    const root = renderer!.root;
    const buttonNames = root
      .findAllByType("button")
      .map((button) => button.children.join(""));
    assert.ok(buttonNames.includes("Play"));
    assert.ok(!buttonNames.includes("Prepare"));
    assert.ok(!buttonNames.includes("Scenes"));
    assert.ok(!buttonNames.includes("GM events"));
    assert.match(JSON.stringify(renderer!.toJSON()), /Combat surface/);
    await act(async () => renderer!.unmount());
  }
});

test("shell landmarks support skip navigation and keep map-first mobile DOM order", async () => {
  let renderer: TestRenderer.ReactTestRenderer;
  await act(async () => {
    renderer = TestRenderer.create(
      createElement(VttShell, {
        role: "gm",
        worldName: "Northwatch",
        sceneName: "Sable Vault",
        connectionLabel: "Reconnecting",
        mapSlot: "Map",
        actionSlot: "Actions",
        initiativeSlot: "Initiative",
        panels,
      }),
    );
  });
  const root = renderer!.root;
  assert.deepEqual(
    root.findAllByType("a").map((link) => link.props.href),
    ["#vtt-map", "#vtt-actions", "#vtt-workspace-panel-combat"],
  );
  assert.equal(
    root.findByProps({ id: "vtt-workspace-panel-combat" }).props.tabIndex,
    -1,
  );
  await act(async () => findButton(root, "Chat").props.onClick());
  assert.equal(
    root.findAllByType("a")[2].props.href,
    "#vtt-workspace-panel-chat",
  );
  assert.equal(
    root.findByProps({ id: "vtt-workspace-panel-chat" }).props.tabIndex,
    -1,
  );
  assert.equal(
    root.findByProps({ "aria-label": "Virtual tabletop status" }).type,
    "header",
  );
  assert.equal(root.findByProps({ role: "status" }).children.join(""), "Reconnecting");
  assert.equal(
    root.findByProps({ className: "vtt-shell-workspace-announcement" }).children.join(""),
    "Play workspace · Chat panel",
  );
  assert.equal(
    root
      .findByProps({ id: "vtt-workspace-panel-chat" })
      .findByProps({ className: "vtt-shell-panel-title" })
      .children.join(""),
    "Chat",
  );
  assert.deepEqual(
    root
      .findAll(
        (node) =>
          node.props.id === "vtt-map" ||
          node.props.id === "vtt-actions" ||
          node.props.id === "vtt-initiative" ||
          node.props.className === "vtt-shell-panel-dock",
      )
      .map((node) => node.props.id ?? node.props.className),
    ["vtt-map", "vtt-actions", "vtt-initiative", "vtt-shell-panel-dock"],
  );
  assert.match(JSON.stringify(renderer!.toJSON()), /DND Sim VTT/);
  await act(async () => renderer!.unmount());
});

test("compact workspace preserves the stage, initiative, panel DOM order visually", () => {
  const css = readFileSync(new URL("../app/globals.css", import.meta.url), "utf8");
  assert.match(
    css,
    /@media \(max-width: 820px\)[\s\S]*?grid-template-areas:\s*"stage"\s*"initiative"\s*"dock";/,
  );
});

test("workspace tabs support roving Arrow, Home, and End keyboard navigation", async () => {
  let renderer: TestRenderer.ReactTestRenderer;
  await act(async () => {
    renderer = TestRenderer.create(
      createElement(VttShell, {
        role: "player",
        worldName: "Northwatch",
        sceneName: "Sable Vault",
        connectionLabel: "Live",
        mapSlot: "Map",
        actionSlot: "Actions",
        panels,
      }),
    );
  });
  const root = renderer!.root;
  const tab = (name: string) =>
    root.findAllByProps({ role: "tab" }).find((item) => item.children.join("") === name)!;
  let focused = "";

  await act(async () =>
    tab("Combat").props.onKeyDown({
      key: "ArrowRight",
      preventDefault() {},
      currentTarget: { parentElement: { querySelector: () => ({ focus: () => { focused = "Activity"; } }) } },
    }),
  );
  assert.equal(focused, "Activity");
  assert.equal(tab("Activity").props["aria-selected"], true);

  await act(async () =>
    tab("Activity").props.onKeyDown({
      key: "End",
      preventDefault() {},
      currentTarget: { parentElement: { querySelector: () => ({ focus: () => { focused = "Events"; } }) } },
    }),
  );
  assert.equal(focused, "Events");
  assert.equal(tab("Events").props["aria-selected"], true);

  await act(async () =>
    tab("Events").props.onKeyDown({
      key: "Home",
      preventDefault() {},
      currentTarget: { parentElement: { querySelector: () => ({ focus: () => { focused = "Combat"; } }) } },
    }),
  );
  assert.equal(focused, "Combat");
  assert.equal(tab("Combat").props["aria-selected"], true);
  await act(async () => renderer!.unmount());
});

test("shell restores only valid injected local preferences", async () => {
  const writes: string[] = [];
  const storage: VttWorkspacePreferenceStorage = {
    read: () => '{"mode":"prepare","panel_id":"visibility"}',
    write: (value) => writes.push(value),
  };
  let renderer: TestRenderer.ReactTestRenderer;
  await act(async () => {
    renderer = TestRenderer.create(
      createElement(VttShell, {
        role: "gm",
        worldName: "Northwatch",
        connectionLabel: "Live",
        mapSlot: "Map",
        actionSlot: "Actions",
        initiativeSlot: "Initiative",
        panels,
        preferenceStorage: storage,
      }),
    );
  });
  assert.match(JSON.stringify(renderer!.toJSON()), /Visibility surface/);
  assert.deepEqual(writes, ['{"mode":"prepare","panel_id":"visibility"}']);
  await act(async () => renderer!.unmount());
});

test("authorized panels stay mounted across navigation and GM panels leave on role downgrade", async () => {
  const mounts = new Map<string, number>();
  const unmounts = new Map<string, number>();
  function PanelProbe({ name }: { name: string }) {
    useEffect(() => {
      mounts.set(name, (mounts.get(name) ?? 0) + 1);
      return () => {
        unmounts.set(name, (unmounts.get(name) ?? 0) + 1);
      };
    }, [name]);
    return createElement("p", null, `${name} panel`);
  }
  const stablePanels: VttShellPanel[] = [
    {
      id: "chat",
      label: "Chat",
      modes: ["play"],
      content: createElement(PanelProbe, { name: "chat" }),
    },
    {
      id: "journal",
      label: "Journal",
      modes: ["play", "prepare"],
      content: createElement(PanelProbe, { name: "journal" }),
    },
    {
      id: "scenes",
      label: "Scenes",
      modes: ["prepare"],
      roles: ["gm"],
      content: createElement(PanelProbe, { name: "scenes" }),
    },
  ];
  const shellProps = {
    worldName: "Northwatch",
    connectionLabel: "Live",
    mapSlot: "Map",
    actionSlot: "Actions",
    panels: stablePanels,
  };
  let renderer: TestRenderer.ReactTestRenderer;
  await act(async () => {
    renderer = TestRenderer.create(
      createElement(VttShell, { ...shellProps, role: "gm" }),
    );
  });
  const root = renderer!.root;
  assert.deepEqual(Object.fromEntries(mounts), { chat: 1, journal: 1, scenes: 1 });
  assert.equal(root.findByProps({ "data-panel-id": "chat" }).props.hidden, false);
  assert.equal(root.findByProps({ "data-panel-id": "journal" }).props.hidden, true);
  assert.equal(root.findByProps({ "data-panel-id": "scenes" }).props.hidden, true);

  await act(async () => findButton(root, "Journal").props.onClick());
  await act(async () => findButton(root, "Prepare").props.onClick());
  await act(async () => findButton(root, "Scenes").props.onClick());
  assert.deepEqual(Object.fromEntries(mounts), { chat: 1, journal: 1, scenes: 1 });
  assert.deepEqual(Object.fromEntries(unmounts), {});

  await act(async () => {
    renderer!.update(createElement(VttShell, { ...shellProps, role: "player" }));
  });
  assert.equal(root.findAllByProps({ "data-panel-id": "scenes" }).length, 0);
  assert.equal(unmounts.get("scenes"), 1);
  assert.equal(unmounts.get("chat") ?? 0, 0);
  assert.equal(unmounts.get("journal") ?? 0, 0);

  await act(async () => renderer!.unmount());
});
