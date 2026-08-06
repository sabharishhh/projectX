import { API_BASE as DEFAULT_API_BASE } from "../config.ts";
const STREAM_IDLE_TIMEOUT_MS = 200000;

async function loadMessagesFor(chatId: string, API_BASE: string) {
  const res = await fetch(`${API_BASE}/api/messages/${chatId}`);
  const raw = await res.json();
  return raw.map((msg: any) => {
    if (msg.activity) {
      msg.activity = msg.activity.filter((a: any) => a.kind !== "searching" && a.kind !== "skill");
    }
    return msg;
  });
}


export interface ChatSession {
  messages: any[];
  streaming: boolean;
  processing: boolean;
  input: string;
}

const sessions = new Map<string, ChatSession>();

function createSession(): ChatSession {
  let session = $state({ messages: [], streaming: false, processing: false, input: "" });
  return session;
}

export function getSession(chatId: string, API_BASE = DEFAULT_API_BASE): ChatSession {
  if (!sessions.has(chatId)) {
    const session = createSession();
    sessions.set(chatId, session);
    loadMessagesFor(chatId, API_BASE).then((msgs) => {
      if (msgs.length) session.messages = msgs;
    });
  }
  return sessions.get(chatId)!;
}

export async function clearChat(chatId: string, API_BASE: string) {
  await fetch(`${API_BASE}/api/messages/${chatId}`, { method: "DELETE" });
  getSession(chatId).messages = [];
}

export function closeSession(chatId: string) {
  sessions.delete(chatId);
}

async function simulateReveal(msg: any, fullText: string) {
  const chunkSize = 3, delayMs = 12;
  for (let idx = 0; idx < fullText.length; idx += chunkSize) {
    msg.content += fullText.slice(idx, idx + chunkSize);
    await new Promise((r) => setTimeout(r, delayMs));
  }
}

class StreamIdleTimeoutError extends Error {
  constructor() { super("STREAM_IDLE_TIMEOUT"); this.name = "StreamIdleTimeoutError"; }
}

function readWithIdleTimeout(reader: ReadableStreamDefaultReader<Uint8Array>) {
  let timer: ReturnType<typeof setTimeout>;
  const timeout = new Promise<never>((_, reject) => {
    timer = setTimeout(() => reject(new StreamIdleTimeoutError()), STREAM_IDLE_TIMEOUT_MS);
  });
  return Promise.race([reader.read(), timeout]).finally(() => clearTimeout(timer));
}

export async function sendMessage(
  chatId: string,
  API_BASE: string,
  overrideText?: string,
  hooks: { onMemoryWrite?: () => void } = {}
) {
  const session = getSession(chatId);
  const text = overrideText ?? session.input;
  if (!text.trim() || session.streaming) return;

  session.messages.push({ role: "user", content: text, created_at: new Date().toISOString() });
  session.input = "";
  session.streaming = true;
  session.processing = true;

  const i = session.messages.length;
  session.messages.push({ role: "assistant", content: "", activity: [], error: null, startedAt: Date.now(), settledAt: null, created_at: new Date().toISOString() });

  let reader: ReadableStreamDefaultReader<Uint8Array> | null = null;

  try {
    const response = await fetch(`${API_BASE}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ conversation_id: chatId, message: text }),
    });

    reader = response.body!.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await readWithIdleTimeout(reader);
      session.processing = false;
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n\n");
      buffer = lines.pop()!;

      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        const ev = JSON.parse(line.slice(6));
        const msg = session.messages[i];

        if (ev.type === "text") {
          if (msg.settledAt == null) msg.settledAt = Date.now();
          msg.activity = msg.activity.filter(
            (a: any) => a.kind !== "searching" && a.kind !== "skill" && a.kind !== "correction_check"
          );
          ev.reveal === "simulated" ? await simulateReveal(msg, ev.value) : (msg.content += ev.value);
        } else if (ev.type === "activity") {
          if (["search", "search_failed", "memory_read", "memory_write"].includes(ev.event.kind)) {
            msg.activity = msg.activity.filter((a: any) => a.kind !== "searching" && a.kind !== "skill");
          }
          msg.activity.push({ ...ev.event, open: false });
          if (ev.event.kind === "memory_write") hooks.onMemoryWrite?.();
        } else if (ev.type === "error") {
          msg.error = ev.message;
        }
      }
    }
  } catch (e: any) {
    session.processing = false;
    if (e instanceof StreamIdleTimeoutError) {
      session.messages[i].error =
        "Lost connection to the server. Please try sending your message again.";
      try { reader?.cancel(); } catch { /* connection may already be dead */ }
    } else {
      session.messages[i].error = e.message || "Something went wrong. Please try again.";
    }
  }
  session.processing = false;
  session.streaming = false;
}