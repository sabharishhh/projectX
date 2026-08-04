import { closeSession } from "./chatSessions.svelte.ts";
import { globalMemory } from "./globalMemory.svelte.ts";
import { API_BASE } from "../config.ts";

export async function reconcileWorkspaceWithConversations() {
  const validIds = new Set(globalMemory.conversations.map((c) => c.conversation_id));
  const candidates = [];
  for (const pane of workspace.panes) {
    for (const chatId of pane.tabs) {
      if (!validIds.has(chatId)) candidates.push(chatId);
    }
  }
  if (!candidates.length) return;

  for (const chatId of candidates) {
    try {
      const res = await fetch(`${API_BASE}/api/messages/${chatId}`);
      const messages = await res.json();
      if (Array.isArray(messages) && messages.length === 0) {
        removeChatEverywhere(chatId);
      }
      // non-empty history + absent from list = confirmed deletion elsewhere
      else if (Array.isArray(messages) && messages.length > 0) {
        removeChatEverywhere(chatId);
      }
    } catch {
      // fetch failed — leave the tab alone rather than guess
    }
  }
}

export interface Pane {
  id: string;
  tabs: string[];
  activeTabId: string | null;
}

export const workspace = $state({ panes: [], activePaneId: null });

function newPaneId() {
  return crypto.randomUUID();
}

const WORKSPACE_STORAGE_KEY = "loki-workspace-layout";

function saveWorkspace() {
  if (workspace.panes.length === 0) return; // never overwrite a real saved layout with a transient empty state
  try {
    localStorage.setItem(WORKSPACE_STORAGE_KEY, JSON.stringify({
      panes: workspace.panes.map((p) => ({ id: p.id, tabs: p.tabs, activeTabId: p.activeTabId })),
      activePaneId: workspace.activePaneId,
    }));
  } catch {}
}

function loadStoredWorkspace() {
  try {
    const raw = localStorage.getItem(WORKSPACE_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!parsed?.panes?.length) return null;
    return parsed;
  } catch {
    return null;
  }
}

$effect.root(() => {
  $effect(() => {
    // reading these inside the effect is what makes it re-run on every layout change
    workspace.panes.map((p) => ({ id: p.id, tabs: [...p.tabs], activeTabId: p.activeTabId }));
    workspace.activePaneId;
    saveWorkspace();
  });
});

export function initWorkspace(initialChatId) {
  if (workspace.panes.length) return;
  const stored = loadStoredWorkspace();
  if (stored) {
    workspace.panes = stored.panes;
    workspace.activePaneId = stored.activePaneId ?? stored.panes[0]?.id ?? null;
    return;
  }
  const pane = { id: newPaneId(), tabs: [initialChatId], activeTabId: initialChatId };
  workspace.panes = [pane];
  workspace.activePaneId = pane.id;
}

export function activePane() {
  return workspace.panes.find((p) => p.id === workspace.activePaneId);
}

export function activeChatId() {
  return activePane()?.activeTabId ?? null;
}

export function openTab(chatId, paneId = workspace.activePaneId) {
  const existingPane = workspace.panes.find((p) => p.tabs.includes(chatId));
  if (existingPane) {
    existingPane.activeTabId = chatId;
    workspace.activePaneId = existingPane.id;
    return;
  }
  const pane = workspace.panes.find((p) => p.id === paneId) ?? workspace.panes[0];
  if (!pane) return;
  pane.tabs.push(chatId);
  pane.activeTabId = chatId;
  workspace.activePaneId = pane.id;
}

export function closeTab(paneId, chatId) {
  const pane = workspace.panes.find((p) => p.id === paneId);
  if (!pane) return;
  pane.tabs = pane.tabs.filter((t) => t !== chatId);
  closeSession(chatId);
  if (pane.activeTabId === chatId) pane.activeTabId = pane.tabs.at(-1) ?? null;
  if (pane.tabs.length === 0 && workspace.panes.length > 1) {
    workspace.panes = workspace.panes.filter((p) => p.id !== paneId);
    if (workspace.activePaneId === paneId) workspace.activePaneId = workspace.panes[0]?.id ?? null;
  }
}

export function selectTab(paneId, chatId) {
  const pane = workspace.panes.find((p) => p.id === paneId);
  if (!pane) return;
  pane.activeTabId = chatId;
  workspace.activePaneId = paneId;
}

export function reorderTabs(paneId, fromChatId, toChatId, side) {
  const pane = workspace.panes.find((p) => p.id === paneId);
  if (!pane) return;
  const arr = pane.tabs;
  const fromIndex = arr.indexOf(fromChatId);
  if (fromIndex === -1) return;
  arr.splice(fromIndex, 1);
  let toIndex = arr.indexOf(toChatId);
  if (toIndex === -1) { arr.splice(fromIndex, 0, fromChatId); return; }
  if (side === 'after') toIndex += 1;
  arr.splice(toIndex, 0, fromChatId);
}

export function moveTabToPane(fromPaneId, chatId, toPaneId, targetChatId, side) {
  const fromPane = workspace.panes.find((p) => p.id === fromPaneId);
  const toPane = workspace.panes.find((p) => p.id === toPaneId);
  if (!fromPane || !toPane) return;

  if (fromPaneId === toPaneId) {
    reorderTabs(toPaneId, chatId, targetChatId, side);
    return;
  }

  fromPane.tabs = fromPane.tabs.filter((t) => t !== chatId);
  if (fromPane.activeTabId === chatId) fromPane.activeTabId = fromPane.tabs.at(-1) ?? null;
  if (fromPane.tabs.length === 0 && workspace.panes.length > 1) {
    workspace.panes = workspace.panes.filter((p) => p.id !== fromPaneId);
    if (workspace.activePaneId === fromPaneId) workspace.activePaneId = workspace.panes[0]?.id ?? null;
  }

  if (!toPane.tabs.includes(chatId)) {
    let toIndex = targetChatId ? toPane.tabs.indexOf(targetChatId) : toPane.tabs.length;
    if (toIndex === -1) toIndex = toPane.tabs.length;
    if (side === 'after') toIndex += 1;
    toPane.tabs.splice(toIndex, 0, chatId);
  }
  toPane.activeTabId = chatId;
  workspace.activePaneId = toPaneId;
}

export function splitPane() {
  if (workspace.panes.length >= 3) return;
  const current = activeChatId();
  const pane = { id: newPaneId(), tabs: current ? [current] : [], activeTabId: current };
  workspace.panes.push(pane);
  workspace.activePaneId = pane.id;
}

export function removeChatEverywhere(chatId) {
  for (const pane of [...workspace.panes]) {
    if (pane.tabs.includes(chatId)) closeTab(pane.id, chatId);
  }
}

export const uiState = $state({ panelOpen: false });

export function openMemoryPanelForChat(chatId) {
  const pane = workspace.panes.find((p) => p.tabs.includes(chatId));
  if (pane) workspace.activePaneId = pane.id;
  uiState.panelOpen = true;
}

export const composeEditState = $state({ unit: null });

export function beginMemoryEdit(unit) {
  composeEditState.unit = unit;
}

export function cancelMemoryEdit() {
  composeEditState.unit = null;
}

export const dragState = $state({ active: false, chatId: null });

export function startChatDrag(chatId) {
  dragState.active = true;
  dragState.chatId = chatId;
}

export function endChatDrag() {
  dragState.active = false;
  dragState.chatId = null;
}

export function dropChatIntoNewPane(chatId) {
  if (workspace.panes.length >= 3) return;
  const existingPane = workspace.panes.find((p) => p.tabs.includes(chatId));
  if (existingPane) {
    existingPane.activeTabId = chatId;
    workspace.activePaneId = existingPane.id;
    return;
  }
  const pane = { id: newPaneId(), tabs: [chatId], activeTabId: chatId };
  workspace.panes.push(pane);
  workspace.activePaneId = pane.id;
}