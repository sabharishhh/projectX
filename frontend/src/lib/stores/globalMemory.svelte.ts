import { API_BASE } from "../config.ts";
import { MEMORY_BASE } from "../config.ts";

export const globalMemory = $state({ memory: [], history: [], conversations: [] });

export async function loadMemory() {
  try {
    const branches = await (await fetch(`${MEMORY_BASE}/branches`)).json();
    const list = branches.length ? branches : ["main"];
    const results = await Promise.all(
      list.map((b) =>
        fetch(`${MEMORY_BASE}/state?branch=${encodeURIComponent(b)}`)
          .then((r) => r.json())
          .then((units) => units.map((u) => ({ ...u, branch: b })))
      )
    );
    const seen = new Set();
    globalMemory.memory = results.flat().filter((u) => (seen.has(u.hash) ? false : (seen.add(u.hash), true)));
  } catch { globalMemory.memory = []; }
}

export async function loadHistory() {
  try {
    const branches = await (await fetch(`${MEMORY_BASE}/branches`)).json();
    const list = branches.length ? branches : ["main"];
    const results = await Promise.all(
      list.map((b) =>
        fetch(`${MEMORY_BASE}/history?branch=${encodeURIComponent(b)}`)
          .then((r) => r.json())
          .then((c) => c.map((x) => ({ ...x, branch: b })))
      )
    );
    globalMemory.history = results.flat().sort((a, b) => +new Date(b.created_at) - +new Date(a.created_at));
  } catch { globalMemory.history = []; }
}

export async function loadConversations() {
  try { globalMemory.conversations = await (await fetch(`${API_BASE}/api/conversations`)).json(); }
  catch { globalMemory.conversations = []; }
}

export async function clearMemory() {
  await fetch(`${MEMORY_BASE}/reset`, { method: "POST" });
  await Promise.all([loadMemory(), loadHistory()]);
}

export async function editMemoryItem(unit, newContent) {
  const res = await fetch(`${API_BASE}/api/memory/edit`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      hash: unit.hash, branch: unit.branch, new_content: newContent,
      unit_type: unit.unit_type, provenance: unit.provenance,
      deadline: unit.deadline ?? null, commitment_status: unit.commitment_status ?? null,
    }),
  });
  const data = await res.json();
  if (data.ok) { await loadMemory(); await loadHistory(); }
}