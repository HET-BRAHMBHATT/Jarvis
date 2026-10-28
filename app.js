(() => {
  "use strict";

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));
  const CHAT_KEY = "jarvis.field.chat.v1";
  const SPEECH_KEY = "jarvis.field.speech.v1";
  const TIMER_KEY = "jarvis.field.timer.v1";
  const NOTES_KEY = "jarvis.field.notes.v1";
  const allowedHosts = new Set(["www.youtube.com", "www.google.com", "open.spotify.com", "github.com", "www.wikipedia.org", "maps.google.com"]);
  function storageGet(key) { try { return window.localStorage.getItem(key); } catch (_) { return null; } }
  function readBrowserNotes() {
    try {
      const value = JSON.parse(window.localStorage.getItem(NOTES_KEY) || "[]");
      return Array.isArray(value) ? value.filter(note => note && typeof note.id === "string" && typeof note.text === "string").slice(-100) : [];
    } catch (_) { return []; }
  }
  function writeBrowserNotes(notes) {
    try {
      window.localStorage.setItem(NOTES_KEY, JSON.stringify(notes.slice(-100)));
      return true;
    } catch (_) { return false; }
  }
  const history = [];
  let currentMode = "local";
  let notesMode = "server";
  let busy = false;
  let recognition = null;
  let micStream = null;
  let micPermissionStatus = null;
  let micGrantedForPage = false;
  let voiceSessionActive = false;
  let micRestartTimer = null;
  let micStarting = false;
  let currentUtterance = null;
  let listening = false;
  let speechEnabled = storageGet(SPEECH_KEY) === "true";
  let timerEnd = Number(storageGet(TIMER_KEY) || 0);
  let timerInterval = null;

  function showToast(message, isError = false) {
    const region = $("#toast-region");
    const toast = document.createElement("div");
    toast.className = isError ? "toast toast-error" : "toast";
    toast.textContent = message;
    region.appendChild(toast);
    window.setTimeout(() => toast.remove(), 4200);
  }

  function displayTime(date = new Date()) {
    return date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  }

  function renderMessage(role, text, options = {}) {
    const message = document.createElement("article");
    message.className = "message " + role + (options.error ? " message-error" : "");
    const avatar = document.createElement("div");
    avatar.className = "message-avatar";
    avatar.textContent = role === "user" ? "Y" : "J";
    const body = document.createElement("div");
    body.className = "message-body";
    const meta = document.createElement("div");
    meta.className = "message-meta";
    const label = document.createElement("span");
    label.textContent = role === "user" ? "YOU" : "J.A.R.V.I.S.";
    const stamp = document.createElement("time");
    stamp.textContent = displayTime();
    meta.append(label, stamp);
    const bubble = document.createElement("div");
    bubble.className = "message-bubble";
    bubble.textContent = text;
    body.append(meta, bubble);

    if (options.action && options.action.type === "open_site") {
      try {
        const url = new URL(options.action.url);
        if (url.protocol === "https:" && allowedHosts.has(url.hostname)) {
          const link = document.createElement("a");
          link.href = url.href;
          link.target = "_blank";
          link.rel = "noopener noreferrer";
          link.className = "message-action-link";
          link.textContent = "Open " + url.hostname.replace(/^www\./, "") + " ↗";
          bubble.appendChild(document.createElement("br"));
          bubble.appendChild(link);
        }
      } catch (_) {
        // Ignore malformed action data.
      }
    }

    message.append(avatar, body);
    $("#messages").appendChild(message);
    $("#chat-scroll").scrollTop = $("#chat-scroll").scrollHeight;
    return message;
  }

  function persistChat() {
    try {
      localStorage.setItem(CHAT_KEY, JSON.stringify(history.slice(-60)));
    } catch (_) {
      showToast("This browser could not save the local chat history.", true);
    }
  }

  function addToHistory(role, content) {
    history.push({ role, content });
    if (history.length > 60) history.splice(0, history.length - 60);
    persistChat();
  }

  function seedChat() {
    let saved = [];
    try {
      const parsed = JSON.parse(localStorage.getItem(CHAT_KEY) || "[]");
      if (Array.isArray(parsed)) {        saved = parsed.filter(item =>
          item && (item.role === "user" || item.role === "assistant") &&
          typeof item.content === "string" && item.content.trim()
        ).slice(-40);
      }
    } catch (_) {
      saved = [];
    }
    if (saved.length) {
      saved.forEach(item => {
        history.push({ role: item.role, content: item.content });
        renderMessage(item.role, item.content);
      });
    } else {
      const welcome = "Hello. I’m J.A.R.V.I.S., your personal field assistant. I can help with notes, timers, arithmetic, your local clock, and a few trusted shortcuts. Try a prompt below to begin.";
      history.push({ role: "assistant", content: welcome });
      renderMessage("assistant", welcome);
      persistChat();
    }
  }

  async function requestJson(path, options = {}) {
    const response = await fetch(path, {
      cache: "no-store",
      ...options,
      headers: { "Content-Type": "application/json", ...(options.headers || {}) }
    });
    let payload;
    try { payload = await response.json(); }
    catch (_) { throw new Error("The local assistant returned an unreadable response."); }
    if (!response.ok) throw new Error(payload.error || "The request could not be completed.");
    return payload;
  }

  function setMode(mode, model, configuredOnly = false) {
    currentMode = mode === "openai" ? "openai" : "local";
    const cloud = currentMode === "openai";
    const aiState = configuredOnly ? "CONFIGURED" : "AI READY";
    $("#header-status").textContent = cloud ? (configuredOnly ? "AI CONFIGURED" : "AI READY") : "LOCAL READY";
    $("#chat-mode-chip").lastChild.textContent = cloud ? " OPENAI" : " LOCAL";
    $("#ai-stat-title").textContent = cloud ? (configuredOnly ? "OpenAI key configured" : "OpenAI chat connected") : "Local command mode";
    $("#ai-stat-state").textContent = cloud ? aiState : "LOCAL";
    $("#rail-ai-state").textContent = cloud ? (configuredOnly ? "Configured" : "OpenAI chat") : "Local";
    $("#sidebar-mode-copy").textContent = cloud
      ? (configuredOnly ? "An API key is set; account credits and model access are checked when you chat." : "Open-ended chat sends your prompt to OpenAI.")
      : "Your command core is running on this device.";
    $("#health-ai").textContent = cloud ? aiState : "LOCAL";
    $("#health-ai-detail").textContent = cloud
      ? (configuredOnly ? "Key found; live API access is checked on request" : "Your prompts go to OpenAI")
      : "Built-in local commands";
    $("#dialog-mode").textContent = cloud
      ? (configuredOnly ? "OpenAI key configured; live access is checked when you chat" : "OpenAI chat is connected")
      : "Local command mode";
    $("#dialog-model").textContent = cloud ? (model || "MODEL CONFIGURED") : "NO KEY REQUIRED";
  }

  async function refreshStatus() {
    try {
      const status = await requestJson("/api/health");
      notesMode = status.notesMode === "browser" ? "browser" : "server";
      setMode(status.mode, status.model, status.mode === "openai");
      $("#header-status").textContent = status.status === "online" ? (status.mode === "openai" ? "AI READY" : "CORE READY") : "CHECK STATUS";
      $("#rail-core-state").textContent = status.status === "online" ? "Online" : "Unavailable";
      $("#health-server").textContent = status.status === "online" ? "ONLINE" : "OFFLINE";
      await refreshNotes();
    } catch (error) {
      $("#header-status").textContent = "OFFLINE";
      $("#rail-core-state").textContent = "Unavailable";
      $("#health-server").textContent = "OFFLINE";
      showToast("Can’t reach the local assistant. Keep the server window open and refresh.", true);
    }
  }

  function formatNoteDate(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "SAVED ON THIS DEVICE";
    return date.toLocaleString([], { dateStyle: "medium", timeStyle: "short" }).toUpperCase();
  }

  function createNoteElement(note) {
    const row = document.createElement("article");
    row.className = "note-item";    const symbol = document.createElement("span");
    symbol.className = "note-symbol";
    symbol.textContent = "◈";
    const main = document.createElement("div");
    main.style.minWidth = "0";
    main.style.flex = "1";
    const text = document.createElement("p");
    text.className = "note-text";
    text.textContent = note.text;
    const time = document.createElement("time");
    time.className = "note-time";
    time.textContent = formatNoteDate(note.created);
    main.append(text, time);
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "delete-note";
    remove.setAttribute("aria-label", "Remove note");
    remove.title = "Remove this note";
    remove.textContent = "×";
    remove.addEventListener("click", async () => {
      if (!window.confirm("Remove this note from the local Memory Vault?")) return;
      try {
        if (notesMode === "browser") {
          const remaining = readBrowserNotes().filter(item => item.id !== note.id);
          if (!writeBrowserNotes(remaining)) throw new Error("This browser could not update its saved notes.");
        } else {
          await requestJson("/api/notes", {
            method: "POST",
            body: JSON.stringify({ action: "delete", id: note.id })
          });
        }
        await refreshNotes();
        showToast("Note removed from this device.");
      } catch (error) {
        showToast(error.message, true);
      }
    });
    row.append(symbol, main, remove);
    return row;
  }

  async function refreshNotes() {
    const payload = notesMode === "browser" ? { notes: readBrowserNotes() } : await requestJson("/api/notes");
    const notes = Array.isArray(payload.notes) ? payload.notes : [];
    $("#nav-note-count").textContent = String(notes.length);
    $("#stat-note-count").textContent = String(notes.length);
    $("#vault-count").textContent = String(notes.length).padStart(2, "0");
    $("#memory-count-label").textContent = notes.length
      ? notes.length + (notes.length === 1 ? " note stored on this device." : " notes stored on this device.")
      : "Your vault is ready.";
    const list = $("#notes-list");
    list.replaceChildren();
    if (!notes.length) {
      const empty = document.createElement("div");
      empty.className = "notes-empty";
      empty.textContent = "Your vault is quiet for now. Add a note or say “remember …” in the command channel.";
      list.appendChild(empty);
    } else {
      notes.slice().reverse().forEach(note => list.appendChild(createNoteElement(note)));
    }
    const preview = $("#memory-preview-list");
    preview.replaceChildren();
    if (!notes.length) {
      const empty = document.createElement("div");
      empty.className = "empty-memory";
      const icon = document.createElement("span");
      icon.textContent = "✧";
      const copy = document.createElement("p");
      copy.textContent = "A little room for things you’d like to remember.";
      empty.append(icon, copy);
      preview.appendChild(empty);
    } else {
      notes.slice(-2).reverse().forEach(note => {
        const item = document.createElement("div");
        item.className = "preview-note";
        item.textContent = note.text;
        preview.appendChild(item);
      });
    }
  }

  async function sendMessage(rawText) {
    const text = String(rawText || "").trim();
    if (!text || busy) return;
    busy = true;
    const input = $("#message-input");
    input.value = "";
    renderMessage("user", text);
    addToHistory("user", text);
    const prior = history.slice(0, -1).filter(item => item.role === "user" || item.role === "assistant").slice(-8);
    $("#typing-row").hidden = false;
    $("#chat-scroll").scrollTop = $("#chat-scroll").scrollHeight;    $("#chat-form").querySelector("button[type=submit]").disabled = true;
    try {
      const response = await requestJson("/api/chat", {
        method: "POST",
        body: JSON.stringify({ message: text, history: prior })
      });
      $("#typing-row").hidden = true;
      const reply = String(response.reply || "I don’t have a reply for that yet.");
      renderMessage("assistant", reply, { action: response.action });
      addToHistory("assistant", reply);
      if (response.source === "openai") setMode("openai");
      if (response.action) await runAction(response.action);
      if (speechEnabled) speak(reply);
    } catch (error) {
      $("#typing-row").hidden = true;
      renderMessage("assistant", error.message || "I couldn’t complete that request.", { error: true });
      showToast("The request did not complete.", true);
    } finally {
      busy = false;
      $("#chat-form").querySelector("button[type=submit]").disabled = false;
      input.focus();
    }
  }

  async function runAction(action) {
    if (!action || typeof action.type !== "string") return;
    if (action.type === "timer") {
      startTimer(Number(action.seconds), String(action.label || "Timer"));
    } else if (action.type === "timer_error") {
      showToast(String(action.message || "Timer could not be set."), true);
    } else if (action.type === "notes_refresh") {
      await refreshNotes();
      showToast("Saved in your Memory Vault on this device.");
    } else if (action.type === "notes_save_browser") {
      const noteText = String(action.text || "").replace(/\s+/g, " ").trim().slice(0, 600);
      if (!noteText) return;
      const notes = readBrowserNotes();
      notes.push({
        id: (window.crypto && window.crypto.randomUUID) ? window.crypto.randomUUID() : Date.now().toString(36) + Math.random().toString(36).slice(2, 10),
        text: noteText,
        created: new Date().toISOString()
      });
      if (!writeBrowserNotes(notes)) throw new Error("This browser could not save the note.");
      await refreshNotes();
      showToast("Saved in this browser’s Memory Vault.");
    } else if (action.type === "show_memory") {
      setView("memory");
      await refreshNotes();
    } else if (action.type === "open_site") {
      try {
        const url = new URL(action.url);
        if (url.protocol !== "https:" || !allowedHosts.has(url.hostname)) return;
        const opened = window.open(url.href, "_blank", "noopener,noreferrer");
        if (!opened) showToast("Use the secure link in the reply to open the site.");
      } catch (_) {
        showToast("That site could not be opened.", true);
      }
    }
  }

  function timerLabel(seconds) {
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const secs = seconds % 60;
    if (hours) return String(hours).padStart(2, "0") + ":" + String(minutes).padStart(2, "0") + ":" + String(secs).padStart(2, "0");
    return String(minutes).padStart(2, "0") + ":" + String(secs).padStart(2, "0");
  }

  function startTimer(seconds, label) {
    if (!Number.isFinite(seconds) || seconds < 1 || seconds > 86400) return;
    timerEnd = Date.now() + seconds * 1000;
    try { localStorage.setItem(TIMER_KEY, String(timerEnd)); } catch (_) {}
    $("#timer-rail-copy").textContent = label + " · " + timerLabel(seconds);
    $("#timer-banner").hidden = false;
    updateTimer();
    if (timerInterval) window.clearInterval(timerInterval);
    timerInterval = window.setInterval(updateTimer, 250);
  }

  function updateTimer() {
    if (!timerEnd) return;
    const seconds = Math.max(0, Math.ceil((timerEnd - Date.now()) / 1000));
    $("#timer-banner-value").textContent = timerLabel(seconds);
    if (seconds <= 0) {
      stopTimer(false);
      showToast("Your timer is complete.");
      $("#timer-rail-copy").textContent = "Complete · set another";
      if (speechEnabled) speak("Your timer is complete.");
    }
  }

  function stopTimer(announce = true) {
    timerEnd = 0;
    try { localStorage.removeItem(TIMER_KEY); } catch (_) {}
    if (timerInterval) window.clearInterval(timerInterval);    timerInterval = null;
    $("#timer-banner").hidden = true;
    if (announce) {
      $("#timer-rail-copy").textContent = "Your tab stays open";
      showToast("Timer stopped.");
    }
  }

  function speak(text) {
    if (!("speechSynthesis" in window)) {
      showToast("Speech output is not available in this browser.", true);
      return;
    }
    cancelSpeech();
    const utterance = new SpeechSynthesisUtterance(text.slice(0, 1200));
    utterance.rate = 1.02;
    utterance.pitch = 0.96;
    currentUtterance = utterance;
    $("#stop-speech").disabled = false;
    const finish = () => {
      if (currentUtterance !== utterance) return;
      currentUtterance = null;
      $("#stop-speech").disabled = true;
    };
    utterance.onend = finish;
    utterance.onerror = finish;
    window.speechSynthesis.speak(utterance);
  }

  function cancelSpeech() {
    if (!("speechSynthesis" in window)) return;
    currentUtterance = null;
    window.speechSynthesis.cancel();
    const stopButton = $("#stop-speech");
    if (stopButton) stopButton.disabled = true;
  }

  function updateSpeechButton() {
    const button = $("#tts-toggle");
    if (!button) return;
    button.setAttribute("aria-pressed", String(speechEnabled));
    button.title = speechEnabled ? "Voice replies are on" : "Voice replies are off";
    button.classList.toggle("is-enabled", speechEnabled);
    button.textContent = speechEnabled ? "◖" : "◗";
  }

  function releaseMicrophone() {
    if (!micStream) return;
    micStream.getTracks().forEach(track => track.stop());
    micStream = null;
  }

  async function acquireMicrophoneTrack() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      throw new Error("This browser cannot open the microphone here. Use the local page in a current Chrome or Edge browser.");
    }
    if (navigator.permissions && navigator.permissions.query) {
      try {
        micPermissionStatus = await navigator.permissions.query({ name: "microphone" });
        if (micPermissionStatus.state === "denied") {
          const blocked = new Error("Microphone access is blocked for this page. Set its site permission to Allow, then click the mic.");
          blocked.name = "NotAllowedError";
          throw blocked;
        }
      } catch (error) {
        if (error && error.name === "NotAllowedError") throw error;
        micPermissionStatus = null;
      }
    }
    micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const track = micStream.getAudioTracks()[0];
    if (!track) {
      releaseMicrophone();
      throw new Error("No microphone track is available on this device.");
    }
    return track;
  }

  function setupRecognition() {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    const button = $("#voice-button");
    if (!SpeechRecognition) {
      button.disabled = true;
      button.title = "Voice input is not available in this browser. You can still type.";
      $("#health-voice").textContent = "UNAVAILABLE";
      $("#health-voice-detail").textContent = "Use a current Chrome or Edge browser, or type instead";
      $("#voice-note").textContent = "Voice input is unavailable in this browser; text chat still works.";
      return;
    }

    recognition = new SpeechRecognition();
    recognition.lang = navigator.language || "en-US";
    recognition.interimResults = false;
    recognition.continuous = true;
    recognition.maxAlternatives = 1;
    $("#health-voice").textContent = "READY";
    $("#health-voice-detail").textContent = "Tap once to start hands-free listening; tap again to stop";

    function clearRestartTimer() {
      if (micRestartTimer) {
        window.clearTimeout(micRestartTimer);
        micRestartTimer = null;
      }
    }

    function resetVoiceButton() {
      button.disabled = false;
      button.classList.remove("is-listening");
      button.setAttribute("aria-label", "Start voice input");
      button.title = "Start voice input";
      $("#health-voice-detail").textContent = "Tap once to start hands-free listening; tap again to stop";
    }

    function finishVoiceSession() {
      voiceSessionActive = false;
      clearRestartTimer();
      listening = false;
      micStarting = false;
      releaseMicrophone();
      resetVoiceButton();
      if ($("#health-voice").textContent !== "PERMISSION NEEDED") {
        $("#health-voice").textContent = "READY";
      }
    }

    function stopVoiceSession() {
      voiceSessionActive = false;
      clearRestartTimer();
      cancelSpeech();
      try { recognition.abort(); } catch (_) {}
      finishVoiceSession();
    }

    async function startListening() {
      if (micStarting || listening || voiceSessionActive) return;
      voiceSessionActive = true;
      micStarting = true;
      button.disabled = true;
      button.title = "Connecting microphone...";
      $("#health-voice").textContent = "CONNECTING";
      try {
        const track = micGrantedForPage ? null : await acquireMicrophoneTrack();
        if (!voiceSessionActive) {
          releaseMicrophone();
          return;
        }
        micGrantedForPage = true;
        if (track) recognition.start(track);
        else recognition.start();
        listening = true;
        button.classList.add("is-listening");
        button.setAttribute("aria-label", "Stop voice input");
        button.title = "Listening... tap to stop";
        $("#health-voice").textContent = "LISTENING";
      } catch (error) {
        voiceSessionActive = false;
        releaseMicrophone();
        listening = false;
        const name = error && error.name;
        if (name === "NotAllowedError" || name === "SecurityError") {
          showToast("Allow microphone access for this page once. If the browser keeps asking, set 127.0.0.1 to Allow in site settings.", true);
          $("#health-voice").textContent = "PERMISSION NEEDED";
        } else if (name === "NotFoundError") {
          showToast("No microphone was found. Connect one, then click the mic again.", true);
          $("#health-voice").textContent = "NO DEVICE";
        } else if (name === "NotReadableError") {
          showToast("The microphone is busy or unavailable. Close other apps using it, then click the mic again.", true);
          $("#health-voice").textContent = "UNAVAILABLE";
        } else {
          showToast(error && error.message ? error.message : "Could not start voice input.", true);
          $("#health-voice").textContent = "READY";
        }
      } finally {
        micStarting = false;
        button.disabled = false;
        if (!voiceSessionActive) resetVoiceButton();
      }
    }

    button.addEventListener("click", () => {
      if (voiceSessionActive) {
        stopVoiceSession();
        return;
      }
      startListening();
    });

    recognition.onstart = () => {
      if (!voiceSessionActive) {
        try { recognition.stop(); } catch (_) {}
        return;
      }
      listening = true;
      micStarting = false;
      button.disabled = false;
      button.classList.add("is-listening");
      button.setAttribute("aria-label", "Stop voice input");
      button.title = "Listening... tap to stop";
      $("#health-voice").textContent = "LISTENING";
    };

    recognition.onresult = event => {
      let transcript = "";
      for (let index = event.resultIndex; index < event.results.length; index += 1) {
        const result = event.results[index];
        if (result && result.isFinal && result[0] && result[0].transcript) {
          transcript += result[0].transcript + " ";
        }
      }
      if (transcript.trim()) sendMessage(transcript.trim());
    };

    recognition.onerror = event => {
      if (event.error === "not-allowed" || event.error === "service-not-allowed") {
        voiceSessionActive = false;
        micStarting = false;
        micGrantedForPage = false;
        clearRestartTimer();
        releaseMicrophone();
        const blocked = micPermissionStatus && micPermissionStatus.state === "denied";
        showToast(blocked
          ? "Microphone access is blocked for this page. Set its site permission to Allow."
          : "The browser blocked voice recognition. Allow microphone access for this page in site settings, then click once to listen.", true);
        $("#health-voice").textContent = "PERMISSION NEEDED";
      } else if (event.error !== "no-speech" && event.error !== "aborted") {
        voiceSessionActive = false;
        showToast("Voice input stopped: " + String(event.error || "unknown error") + ".", true);
      }
    };

    recognition.onend = () => {
      listening = false;
      micStarting = false;
      if (!voiceSessionActive) {
        finishVoiceSession();
        return;
      }

      button.disabled = false;
      button.classList.add("is-listening");
      button.setAttribute("aria-label", "Stop voice input");
      button.title = "Reconnecting voice input... tap to stop";
      $("#health-voice").textContent = "CONNECTING";
      clearRestartTimer();
      micRestartTimer = window.setTimeout(() => {
        micRestartTimer = null;
        if (!voiceSessionActive) {
          finishVoiceSession();
          return;
        }
        const track = micStream && micStream.getAudioTracks().find(item => item.readyState === "live");
        try {
          if (track) recognition.start(track);
          else recognition.start();
        } catch (error) {
          voiceSessionActive = false;
          releaseMicrophone();
          resetVoiceButton();
          $("#health-voice").textContent = "READY";
          showToast("Voice input stopped. Tap the mic to start another session.", true);
        }
      }, 300);
    };

    window.addEventListener("pagehide", () => {
      voiceSessionActive = false;
      clearRestartTimer();
      releaseMicrophone();
    }, { once: true });
  }

  function setView(view) {
    const labels = { command: "Command deck", memory: "Memory vault", systems: "System pulse" };    if (!labels[view]) return;
    $$(".view").forEach(section => {
      const active = section.id === "view-" + view;
      section.classList.toggle("is-visible", active);
      section.hidden = !active;
    });
    $$(".nav-link").forEach(button => {
      const active = button.dataset.view === view;
      button.classList.toggle("is-active", active);
      if (active) button.setAttribute("aria-current", "page");
      else button.removeAttribute("aria-current");
    });
    $("#breadcrumb-current").textContent = labels[view];
    if (view === "memory") refreshNotes().catch(error => showToast(error.message, true));
  }

  function updateClock() {
    const now = new Date();
    $("#top-clock").textContent = displayTime(now);
    $("#rail-clock").textContent = displayTime(now);
    $("#top-date").textContent = now.toLocaleDateString([], { month: "short", day: "2-digit" }).toUpperCase();
    $("#rail-date").textContent = now.toLocaleDateString([], { weekday: "long", month: "long", day: "numeric" }).toUpperCase();
    const hour = now.getHours();
    $("#daypart").textContent = hour < 12 ? "morning" : hour < 18 ? "afternoon" : "evening";
  }

  function initialize() {
    updateClock();
    window.setInterval(updateClock, 1000);
    seedChat();
    updateSpeechButton();
    setupRecognition();
    refreshStatus();
    if (timerEnd > Date.now()) {
      startTimer(Math.ceil((timerEnd - Date.now()) / 1000), "Saved timer");
    } else if (timerEnd) {
      stopTimer(false);
    }

    $("#chat-form").addEventListener("submit", event => {
      event.preventDefault();
      sendMessage($("#message-input").value);
    });
    $("#message-input").addEventListener("keydown", event => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        $("#chat-form").requestSubmit();
      }
    });
    $$(".nav-link").forEach(button => button.addEventListener("click", () => setView(button.dataset.view)));
    $$("[data-view]").filter(button => !button.classList.contains("nav-link")).forEach(button =>
      button.addEventListener("click", () => setView(button.dataset.view))
    );
    $$("[data-command], [data-prompt]").forEach(button => button.addEventListener("click", () => {
      const command = button.dataset.command || button.dataset.prompt;
      setView("command");
      sendMessage(command);
    }));
    $("#clear-chat").addEventListener("click", () => {
      if (!window.confirm("Clear the chat history saved in this browser?")) return;
      history.splice(0, history.length);
      $("#messages").replaceChildren();
      try { localStorage.removeItem(CHAT_KEY); } catch (_) {}
      const welcome = "Conversation cleared. I’m ready for a fresh start.";
      history.push({ role: "assistant", content: welcome });
      renderMessage("assistant", welcome);
      persistChat();
    });
    $("#tts-toggle").addEventListener("click", () => {
      speechEnabled = !speechEnabled;
      try { localStorage.setItem(SPEECH_KEY, String(speechEnabled)); } catch (_) {}
      updateSpeechButton();
      if (!speechEnabled) cancelSpeech();
      showToast(speechEnabled ? "Voice replies are on." : "Voice replies are off.");
    });
    $("#stop-speech").addEventListener("click", cancelSpeech);
    $("#note-input").addEventListener("input", event => {
      $("#note-char-count").textContent = event.target.value.length + " / 600";
    });
    $("#note-form").addEventListener("submit", async event => {
      event.preventDefault();      const field = $("#note-input");
      const text = field.value.trim();
      if (!text) {
        showToast("Write a note before saving.", true);
        field.focus();
        return;
      }
      try {
        if (notesMode === "browser") {
          const notes = readBrowserNotes();
          notes.push({
            id: (window.crypto && window.crypto.randomUUID) ? window.crypto.randomUUID() : Date.now().toString(36) + Math.random().toString(36).slice(2, 10),
            text: text.slice(0, 600),
            created: new Date().toISOString()
          });
          if (!writeBrowserNotes(notes)) throw new Error("This browser could not save the note.");
        } else {
          await requestJson("/api/notes", { method: "POST", body: JSON.stringify({ action: "add", text }) });
        }
        field.value = "";
        $("#note-char-count").textContent = "0 / 600";
        await refreshNotes();
        showToast("Saved in your Memory Vault on this device.");
      } catch (error) {
        showToast(error.message, true);
      }
    });
    $("#stop-timer").addEventListener("click", () => stopTimer(true));
    const dialog = $("#settings-dialog");
    $("#open-settings").addEventListener("click", () => dialog.showModal());
    $("#system-settings").addEventListener("click", () => dialog.showModal());
    $$(".close-dialog").forEach(button => button.addEventListener("click", () => dialog.close()));
    dialog.addEventListener("click", event => {
      if (event.target === dialog) dialog.close();
    });
  }

  document.addEventListener("DOMContentLoaded", initialize);
})();

