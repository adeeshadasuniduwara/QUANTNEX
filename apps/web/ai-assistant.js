/* QUANTNEX OpenAI connection settings. Secrets are submitted only to the loopback API. */
(() => {
  const $ = id => document.getElementById(id);
  const form = $("qxAiConfigForm");
  if (!form) return;
  const status = $("qxAiStatus");
  const keyInput = $("qxOpenAiKey");
  const modelInput = $("qxOpenAiModel");
  const webSearchInput = $("qxAiWebSearch");
  const buttons = [$("qxAiSave"), $("qxAiTest"), $("qxAiRemove")];
  const api = "http://127.0.0.1:8000/api/v1/ai";
  const setStatus = (message, bad = false) => {
    status.textContent = message;
    status.dataset.state = bad ? "error" : "ok";
  };
  async function request(path, options = {}) {
    const response = await fetch(api + path, {
      ...options,
      headers: { Accept: "application/json", ...(options.body ? { "Content-Type": "application/json" } : {}), ...(options.headers || {}) },
      cache: "no-store"
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || "OpenAI settings request failed (" + response.status + ").");
    return data;
  }
  function busy(value) { buttons.forEach(button => { button.disabled = value; }); }
  async function refresh() {
    try {
      const data = await request("/status");
      modelInput.value = data.model || "gpt-5.5";
      webSearchInput.checked = Boolean(data.web_search_enabled);
      setStatus(data.configured
        ? "OpenAI connected · " + (data.model || "model configured") + " · API key " + (data.api_key_saved ? "saved encrypted" : "loaded from backend environment")
        : "OpenAI is not connected. Add your API key below.");
      $("qxAiHelp").textContent = data.configured
        ? "AI is ready for Telegram questions. Open your connected bot and send a normal text message; QUANTNEX AI will answer using its product knowledge."
        : "Add an OpenAI API key to activate AI chat in Telegram. Never paste the key into Telegram.";
    } catch (error) { setStatus("Could not load AI status: " + error.message, true); }
  }
  form.addEventListener("submit", async event => {
    event.preventDefault();
    busy(true);
    try {
      const data = await request("/config", {
        method: "POST",
        body: JSON.stringify({
          api_key: keyInput.value.trim(),
          model: modelInput.value.trim() || "gpt-5.5",
          web_search_enabled: webSearchInput.checked
        })
      });
      keyInput.value = "";
      setStatus("AI settings saved securely. API key " + (data.api_key_saved ? "stored encrypted." : "not yet configured."));
      await refresh();
    } catch (error) { setStatus("Could not save AI settings: " + error.message, true); }
    finally { busy(false); }
  });
  $("qxAiTest").addEventListener("click", async () => {
    busy(true); setStatus("Verifying OpenAI key and model access…");
    try {
      const data = await request("/test", { method: "POST" });
      setStatus("✓ " + data.message + " · " + data.model);
    } catch (error) { setStatus("OpenAI connection test failed: " + error.message, true); }
    finally { busy(false); }
  });
  $("qxAiRemove").addEventListener("click", async () => {
    if (!window.confirm("Remove the saved OpenAI API key from this local QUANTNEX workspace?")) return;
    busy(true);
    try {
      await request("/config", { method: "DELETE" });
      keyInput.value = "";
      setStatus("Saved OpenAI API key removed.");
      await refresh();
    } catch (error) { setStatus("Could not remove OpenAI key: " + error.message, true); }
    finally { busy(false); }
  });
  refresh();
})();
