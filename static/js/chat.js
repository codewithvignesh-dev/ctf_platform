(function () {
  const box = document.getElementById("chat-messages");
  const form = document.getElementById("chat-form");
  const input = document.getElementById("chat-input");
  if (!box || !form) return;

  async function loadMessages() {
    try {
      const res = await fetch("/api/chat/messages");
      const data = await res.json();
      if (!data.enabled) return;
      box.innerHTML = data.messages
        .map((m) => `<div><span class="text-neon2">[${m.time}] ${m.user}:</span> ${escapeHtml(m.message)}</div>`)
        .join("");
      box.scrollTop = box.scrollHeight;
    } catch (e) {}
  }

  function escapeHtml(str) {
    const div = document.createElement("div");
    div.innerText = str;
    return div.innerHTML;
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const message = input.value.trim();
    if (!message) return;
    input.value = "";
    await fetch("/api/chat/send", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
    });
    loadMessages();
  });

  loadMessages();
  setInterval(loadMessages, 4000);
})();
