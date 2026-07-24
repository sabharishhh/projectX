<script>
  let messages = $state([]);
  let input = $state("");
  let streaming = $state(false);

  async function sendMessage() {
    if (!input.trim() || streaming) return;

    const userText = input;
    messages.push({ role: "user", content: userText });
    input = "";
    streaming = true;

    // placeholder for the assistant's reply, filled in as tokens arrive
    const assistantMsg = { role: "assistant", content: "" };
    messages.push(assistantMsg);

    const response = await fetch("http://127.0.0.1:8000/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ conversation_id: "default", message: userText }),
    });

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n\n");
      buffer = lines.pop(); // keep any incomplete chunk for next read

      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        const data = line.slice(6);
        if (data === "[DONE]") { streaming = false; continue; }
        assistantMsg.content += JSON.parse(data);
        messages = messages; // trigger reactivity
      }
    }
    streaming = false;
  }

  function handleKeydown(e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  }
</script>

<main>
  <div class="messages">
    {#each messages as msg}
      <div class="msg {msg.role}">{msg.content}</div>
    {/each}
  </div>

  <div class="input-row">
    <textarea
      bind:value={input}
      onkeydown={handleKeydown}
      placeholder="Type a message..."
      disabled={streaming}
    ></textarea>
    <button onclick={sendMessage} disabled={streaming}>Send</button>
  </div>
</main>

<style>
  main {
    display: flex;
    flex-direction: column;
    height: 100vh;
    max-width: 700px;
    margin: 0 auto;
  }
  .messages {
    flex: 1;
    overflow-y: auto;
    padding: 1rem;
  }
  .msg {
    margin-bottom: 0.75rem;
    padding: 0.5rem 0.75rem;
    border-radius: 8px;
    white-space: pre-wrap;
  }
  .msg.user {
    background: #2a2a2a;
    color: white;
    align-self: flex-end;
  }
  .msg.assistant {
    background: #f0f0f0;
  }
  .input-row {
    display: flex;
    gap: 0.5rem;
    padding: 1rem;
    border-top: 1px solid #ddd;
  }
  textarea {
    flex: 1;
    resize: none;
    padding: 0.5rem;
  }
</style>