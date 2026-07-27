
### The Issue

The UI's ephemeral status indicators (specifically "Using research skill") were persisting on the screen after background tasks had finished. While the UI correctly identified the tasks as completed (dimming and italicizing the text via CSS), the frontend JavaScript lacked the logic to actively remove these temporary states from the DOM once concrete data or text began streaming from the backend.

### Steps Taken

1. **Visual Polish:** Updated the CSS keyframe animation for the loading text to use a brightened text color (`var(--text-primary)`) instead of the blue accent color, ensuring better visual distinction.
2. **Diagnosing the DOM Persistence:** Identified that the `sendMessage` function was appending activity states to the `activity` array but not filtering out the temporary ones (`skill`, `searching`) when actual content arrived.
3. **Stream Interception Fix:** Modified the frontend stream parser to proactively scrub `"searching"` and `"skill"` activities the moment a concrete result (like `memory_read` or actual text) is received from the server.
4. **Testing Strategy:** Confirmed that the fix applies to all newly generated chats and opted out of writing a retroactive database patch for legacy messages, choosing instead to clear old chats and test with a clean slate.

### Code Changes

**1. `frontend/src/lib/components/ActivityStrip.svelte**`
Modified the `.pulsing` class gradient to swap the highlight color from the blue accent to `var(--text-primary)`.

```css
  .pulsing {
    background: linear-gradient(
      90deg,
      var(--text-muted) 0%,
      var(--text-muted) 45%,
      var(--text-primary) 50%, /* Swapped from var(--accent) */
      var(--text-muted) 55%,
      var(--text-muted) 100%
    );
    background-size: 300% 100%;
    color: transparent;
    -webkit-background-clip: text;
    background-clip: text;
    animation: shine 3s linear infinite;
  }

  .pulsing i { 
    color: var(--accent); 
    animation: breathe 3s var(--ease-inout) infinite; 
  }

```

**2. `frontend/src/App.svelte**`
Replaced the `sendMessage()` function to include array filtering logic (`messages[i].activity.filter`) when `text` or concrete `activity` events are intercepted from the SSE stream.

```javascript
  async function sendMessage() {
    if (!input.trim() || streaming) return;

    const userText = input;
    messages.push({ role: "user", content: userText });
    input = "";
    streaming = true;

    const i = messages.length;
    messages.push({ role: "assistant", content: "", activity: [], error: null });

    try {
      const response = await fetch(`${API_BASE}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ conversation_id: CONVERSATION_ID, message: userText }),
      });

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n\n");
        buffer = lines.pop();

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const ev = JSON.parse(line.slice(6));

          if (ev.type === "text") {
            messages[i].content += ev.value;
            // 1. Scrub loading states completely when text starts streaming
            messages[i].activity = messages[i].activity.filter(
              (a) => a.kind !== "searching" && a.kind !== "skill"
            );
          } else if (ev.type === "activity") {
            // 2. Scrub loading states completely when ANY concrete result arrives
            if (["search", "search_failed", "memory_read", "memory_write"].includes(ev.event.kind)) {
              messages[i].activity = messages[i].activity.filter(
                (a) => a.kind !== "searching" && a.kind !== "skill"
              );
            }
            messages[i].activity.push({ ...ev.event, open: false });
            if (ev.event.kind === "memory_write") loadMemory();
          } else if (ev.type === "error") {
            messages[i].error = ev.message;
          }
        }
      }
    } catch (e) {
      messages[i].error = e.message;
    }
    streaming = false;
    await loadConversations(); 
  }

```