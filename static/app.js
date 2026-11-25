/* ==========================================================================
   J.A.R.V.I.S. — Frontend HUD Controller (Vanilla ES6+, PWA, Voice, Markdown)
   ========================================================================== */

(() => {
  "use strict";

  // ------------------------------------------------------------------------
  // Estado global da aplicação
  // ------------------------------------------------------------------------
  const ALLOWED_MODELS = [
    "gemini-3.8-flash",
    "gemini-4-hydrogen",
    "gemini-3.5-flash-lite",
    "gemini-4-argon",
  ];
  const DEFAULT_MODEL = "gemini-3.8-flash";

  const STORAGE = {
    PIN: "jarvis_pin",
    MUTED: "jarvis_muted",
    RATE: "jarvis_tts_rate",
    HANDSFREE: "jarvis_handsfree",
    MODEL: "jarvis_model",
  };

  function getStoredModel() {
    const saved = (localStorage.getItem(STORAGE.MODEL) || "").trim();
    return ALLOWED_MODELS.includes(saved) ? saved : null;
  }

  const state = {
    pin: localStorage.getItem(STORAGE.PIN) || "",
    selectedModel: getStoredModel() || DEFAULT_MODEL,
    googleAuth: {
      connected: false,
      configured: false,
      email: null,
    },
    coreStatus: "idle", // idle | listening | processing | speaking
    muted: localStorage.getItem(STORAGE.MUTED) === "true",
    ttsRate: parseFloat(localStorage.getItem(STORAGE.RATE) || "1.12") || 1.12,
    handsFree: localStorage.getItem(STORAGE.HANDSFREE) === "true",
    isSending: false,
    pendingFile: null,
    pendingThumbUrl: null,
    selectedVoice: null,
    deferredInstallPrompt: null,
    activeDrawerTab: "tasks",
    micLevel: 0,
    speechQueue: [],
    isSpeaking: false,
    recognition: null,
    isListening: false,
    audioCtx: null,
    micStream: null,
    analyser: null,
  };

  // ------------------------------------------------------------------------
  // Referências de DOM
  // ------------------------------------------------------------------------
  const el = {
    lockScreen: document.getElementById("lock-screen"),
    lockCard: document.querySelector(".lock-card"),
    pinInput: document.getElementById("pin-input"),
    pinDots: document.getElementById("pin-dots"),
    pinError: document.getElementById("pin-error"),
    pinSubmitBtn: document.getElementById("pin-submit-btn"),
    keypad: document.querySelector(".pin-keypad"),

    appShell: document.getElementById("app-shell"),
    connectionDot: document.getElementById("connection-dot"),
    brtClock: document.getElementById("brt-clock"),
    modelSelect: document.getElementById("model-select"),
    apiWarningChip: document.getElementById("api-warning-chip"),
    googleAuthBtn: document.getElementById("google-auth-btn"),
    googleAuthLabel: document.getElementById("google-auth-label"),
    installPwaBtn: document.getElementById("install-pwa-btn"),
    drawerToggleBtn: document.getElementById("drawer-toggle-btn"),
    pendingBadge: document.getElementById("pending-badge"),
    muteBtnTop: document.getElementById("mute-btn-top"),
    muteBtnPanel: document.getElementById("mute-btn-panel"),
    muteLabel: document.getElementById("mute-label"),
    clearChatBtn: document.getElementById("clear-chat-btn"),
    lockBtn: document.getElementById("lock-btn"),

    coreButton: document.getElementById("core-button"),
    coreCanvas: document.getElementById("core-canvas"),
    coreStatusLabel: document.getElementById("core-status-label"),
    coreSubstatus: document.getElementById("core-substatus"),
    interruptSpeechBtn: document.getElementById("interrupt-speech-btn"),
    handsfreeBtn: document.getElementById("handsfree-btn"),
    ttsRateSelect: document.getElementById("tts-rate-select"),
    modelTag: document.getElementById("model-tag"),
    voiceNameTag: document.getElementById("voice-name-tag"),

    statTasksSub: document.getElementById("stat-tasks-sub"),
    statNotesSub: document.getElementById("stat-notes-sub"),
    statMemoriesSub: document.getElementById("stat-memories-sub"),

    chatPanel: document.getElementById("chat-panel"),
    dropOverlay: document.getElementById("drop-overlay"),
    messagesList: document.getElementById("messages-list"),
    attachmentBar: document.getElementById("attachment-bar"),
    attachmentThumb: document.getElementById("attachment-thumb"),
    attachmentFileBadge: document.getElementById("attachment-file-badge"),
    attachmentName: document.getElementById("attachment-name"),
    attachmentSize: document.getElementById("attachment-size"),
    removeAttachmentBtn: document.getElementById("remove-attachment-btn"),

    chatForm: document.getElementById("chat-form"),
    fileInput: document.getElementById("file-input"),
    attachBtn: document.getElementById("attach-btn"),
    messageInput: document.getElementById("message-input"),
    composerMicBtn: document.getElementById("composer-mic-btn"),
    sendBtn: document.getElementById("send-btn"),

    drawerBackdrop: document.getElementById("drawer-backdrop"),
    hudDrawer: document.getElementById("hud-drawer"),
    drawerCloseBtn: document.getElementById("drawer-close-btn"),
    drawerTabs: document.querySelectorAll(".drawer-tab"),
    tabPanels: {
      tasks: document.getElementById("tab-tasks"),
      memories: document.getElementById("tab-memories"),
      notes: document.getElementById("tab-notes"),
    },

    quickTaskForm: document.getElementById("quick-task-form"),
    taskTitleInput: document.getElementById("task-title-input"),
    taskDeadlineInput: document.getElementById("task-deadline-input"),
    taskPrioritySelect: document.getElementById("task-priority-select"),
    tasksList: document.getElementById("tasks-list"),

    quickMemoryForm: document.getElementById("quick-memory-form"),
    memoryKeyInput: document.getElementById("memory-key-input"),
    memoryCatInput: document.getElementById("memory-cat-input"),
    memoryValInput: document.getElementById("memory-val-input"),
    memorySearchInput: document.getElementById("memory-search-input"),
    memoriesList: document.getElementById("memories-list"),

    quickNoteForm: document.getElementById("quick-note-form"),
    noteTitleInput: document.getElementById("note-title-input"),
    noteTagInput: document.getElementById("note-tag-input"),
    noteContentInput: document.getElementById("note-content-input"),
    notesList: document.getElementById("notes-list"),

    toast: document.getElementById("toast"),
  };

  // ------------------------------------------------------------------------
  // Utilitários gerais
  // ------------------------------------------------------------------------
  let toastTimer = null;
  function showToast(text, duration = 2600) {
    el.toast.textContent = text;
    el.toast.classList.remove("hidden");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.toast.classList.add("hidden"), duration);
  }

  function escapeHtml(str) {
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function formatBytes(bytes) {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
  }

  function formatTimeShort(isoStr) {
    if (!isoStr) return "";
    const d = new Date(isoStr);
    if (Number.isNaN(d.getTime())) return "";
    return new Intl.DateTimeFormat("pt-BR", {
      timeZone: "America/Sao_Paulo",
      hour: "2-digit",
      minute: "2-digit",
    }).format(d);
  }

  function startBrtClock() {
    const fmt = new Intl.DateTimeFormat("pt-BR", {
      timeZone: "America/Sao_Paulo",
      weekday: "short",
      day: "2-digit",
      month: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
    const tick = () => {
      const now = new Date();
      el.brtClock.textContent = fmt.format(now).replace(".", "");
      el.brtClock.setAttribute("datetime", now.toISOString());
    };
    tick();
    setInterval(tick, 10000);
  }

  // ------------------------------------------------------------------------
  // Wrapper autenticado de API (sempre envia X-Jarvis-Pin)
  // ------------------------------------------------------------------------
  async function apiFetch(url, options = {}) {
    const headers = new Headers(options.headers || {});
    headers.set("X-Jarvis-Pin", state.pin);

    const response = await fetch(url, { ...options, headers });

    if (response.status === 401) {
      lockInterface("Sessão bloqueada ou PIN inválido.");
      throw new Error("PIN inválido");
    }

    const contentType = response.headers.get("content-type") || "";
    const data = contentType.includes("application/json")
      ? await response.json()
      : { detail: await response.text() };

    if (!response.ok) {
      throw new Error(data.detail || `Erro HTTP ${response.status}`);
    }
    return data;
  }

  // ------------------------------------------------------------------------
  // Autenticação por PIN (com persistência em localStorage)
  // ------------------------------------------------------------------------
  function renderPinDots(length) {
    const count = Math.max(4, Math.min(length, 8));
    let html = "";
    for (let i = 0; i < count; i++) {
      html += `<span class="pin-dot ${i < length ? "filled" : ""}"></span>`;
    }
    el.pinDots.innerHTML = html;
  }

  function showLockError(msg) {
    el.pinError.textContent = msg;
    el.lockCard.classList.remove("shake");
    void el.lockCard.offsetWidth;
    el.lockCard.classList.add("shake");
  }

  function lockInterface(reason = "") {
    stopListening();
    stopSpeaking();
    state.pin = "";
    localStorage.removeItem(STORAGE.PIN);
    el.pinInput.value = "";
    renderPinDots(0);
    el.pinError.textContent = reason;
    el.appShell.classList.add("hidden");
    el.lockScreen.classList.remove("hidden");
    closeDrawer();
    setTimeout(() => el.pinInput.focus(), 60);
  }

  async function attemptPinUnlock(candidatePin, silent = false) {
    const pin = (candidatePin || "").trim();
    if (!pin) {
      if (!silent) showLockError("Informe o PIN de acesso.");
      return false;
    }

    el.pinSubmitBtn.disabled = true;
    el.pinSubmitBtn.textContent = "Verificando...";

    try {
      const resp = await fetch("/api/auth/verify", {
        method: "POST",
        headers: { "X-Jarvis-Pin": pin },
      });

      if (!resp.ok) {
        if (!silent) {
          showLockError("PIN incorreto. Tente novamente.");
          el.pinInput.value = "";
          renderPinDots(0);
        } else {
          localStorage.removeItem(STORAGE.PIN);
          state.pin = "";
        }
        return false;
      }

      const data = await resp.json();
      state.pin = pin;
      localStorage.setItem(STORAGE.PIN, pin);
      el.pinError.textContent = "";
      el.lockScreen.classList.add("hidden");
      el.appShell.classList.remove("hidden");

      applyServerStatus(data);
      await loadInitialData();
      return true;
    } catch (_err) {
      if (!silent) showLockError("Falha de conexão com o servidor J.A.R.V.I.S.");
      return false;
    } finally {
      el.pinSubmitBtn.disabled = false;
      el.pinSubmitBtn.textContent = "Autenticar Acesso";
    }
  }

  function initPinLock() {
    el.pinInput.addEventListener("input", () => {
      el.pinError.textContent = "";
      renderPinDots(el.pinInput.value.length);
    });

    el.pinInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        attemptPinUnlock(el.pinInput.value);
      }
    });

    el.keypad.addEventListener("click", (e) => {
      const btn = e.target.closest("button");
      if (!btn) return;
      el.pinError.textContent = "";

      if (btn.dataset.key !== undefined) {
        if (el.pinInput.value.length < 16) {
          el.pinInput.value += btn.dataset.key;
          renderPinDots(el.pinInput.value.length);
        }
      } else if (btn.dataset.action === "backspace") {
        el.pinInput.value = el.pinInput.value.slice(0, -1);
        renderPinDots(el.pinInput.value.length);
      } else if (btn.dataset.action === "clear") {
        el.pinInput.value = "";
        renderPinDots(0);
      }
    });

    el.pinSubmitBtn.addEventListener("click", () => attemptPinUnlock(el.pinInput.value));
    el.lockBtn.addEventListener("click", () => lockInterface("Interface bloqueada."));
  }

  // ------------------------------------------------------------------------
  // Núcleo Central Animado em Canvas (Ocioso / Ouvindo / Processando / Falando)
  // ------------------------------------------------------------------------
  const coreAnim = {
    t: 0,
    spin: 0,
    energy: 0.15,
    targetEnergy: 0.15,
  };

  function setCoreState(newState, subtext) {
    state.coreStatus = newState;
    el.coreButton.dataset.state = newState;
    el.composerMicBtn.classList.toggle("recording", newState === "listening");

    const labels = {
      idle: "OCIOSO",
      listening: "OUVINDO",
      processing: "PROCESSANDO",
      speaking: "FALANDO",
    };

    const defaultSubs = {
      idle: state.handsFree
        ? "Modo contínuo pronto — toque para iniciar"
        : "Toque no núcleo para falar",
      listening: "Escutando em pt-BR...",
      processing: "Analisando contexto e ferramentas...",
      speaking: "Transmitindo resposta em voz...",
    };

    el.coreStatusLabel.textContent = labels[newState] || "OCIOSO";
    el.coreSubstatus.textContent = subtext || defaultSubs[newState] || "";
    el.interruptSpeechBtn.classList.toggle("hidden", newState !== "speaking");
  }

  function startCoreCanvasLoop() {
    const canvas = el.coreCanvas;
    const ctx = canvas.getContext("2d");
    const size = 440;
    const cx = size / 2;
    const cy = size / 2;

    function frame() {
      const mode = state.coreStatus;
      coreAnim.t += 0.025;

      // Mede nível real do microfone quando ativo
      if (mode === "listening" && state.analyser) {
        const data = new Uint8Array(state.analyser.frequencyBinCount);
        state.analyser.getByteFrequencyData(data);
        let sum = 0;
        for (let i = 0; i < data.length; i++) sum += data[i];
        const avg = sum / data.length / 255;
        state.micLevel = state.micLevel * 0.72 + avg * 0.28;
      } else {
        state.micLevel *= 0.88;
      }

      if (mode === "idle") {
        coreAnim.targetEnergy = 0.18;
        coreAnim.spin += 0.005;
      } else if (mode === "listening") {
        coreAnim.targetEnergy = 0.55 + Math.min(0.65, state.micLevel * 2.2);
        coreAnim.spin += 0.016;
      } else if (mode === "processing") {
        coreAnim.targetEnergy = 0.72;
        coreAnim.spin += 0.075;
      } else if (mode === "speaking") {
        const pulse = 0.5 + 0.35 * Math.sin(coreAnim.t * 4.8) * Math.cos(coreAnim.t * 2.1);
        coreAnim.targetEnergy = 0.35 + pulse * 0.55;
        coreAnim.spin += 0.024;
      }

      coreAnim.energy += (coreAnim.targetEnergy - coreAnim.energy) * 0.12;

      ctx.clearRect(0, 0, size, size);

      // 1. Halo radial suave
      const haloRadius = 152 + Math.sin(coreAnim.t * 1.4) * 6 + coreAnim.energy * 26;
      const halo = ctx.createRadialGradient(cx, cy, 24, cx, cy, haloRadius);
      halo.addColorStop(0, `rgba(0, 229, 255, ${0.22 + coreAnim.energy * 0.2})`);
      halo.addColorStop(0.55, `rgba(0, 229, 255, ${0.06 + coreAnim.energy * 0.08})`);
      halo.addColorStop(1, "rgba(0, 229, 255, 0)");
      ctx.fillStyle = halo;
      ctx.beginPath();
      ctx.arc(cx, cy, haloRadius, 0, Math.PI * 2);
      ctx.fill();

      // 2. Anel externo de precisão
      ctx.save();
      ctx.translate(cx, cy);
      ctx.rotate(coreAnim.spin * 0.45);
      ctx.strokeStyle = "rgba(0, 229, 255, 0.22)";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(0, 0, 170, 0, Math.PI * 2);
      ctx.stroke();

      // Arcos segmentados de telemetria
      ctx.strokeStyle = mode === "processing"
        ? "rgba(0, 229, 255, 0.92)"
        : "rgba(0, 229, 255, 0.68)";
      ctx.lineWidth = mode === "processing" ? 5 : 3.5;
      ctx.lineCap = "round";
      for (let i = 0; i < 3; i++) {
        const start = i * ((Math.PI * 2) / 3) + 0.22;
        const span = mode === "processing" ? 1.15 : 1.4;
        ctx.beginPath();
        ctx.arc(0, 0, 146, start, start + span);
        ctx.stroke();
      }
      ctx.restore();

      // 3. Anel orbital interno contra-rotativo
      ctx.save();
      ctx.translate(cx, cy);
      ctx.rotate(-coreAnim.spin * (mode === "processing" ? 1.65 : 0.8));
      ctx.strokeStyle = "rgba(238, 244, 255, 0.45)";
      ctx.lineWidth = 2.2;
      ctx.setLineDash(mode === "processing" ? [18, 12] : [6, 14]);
      ctx.beginPath();
      ctx.arc(0, 0, 118, 0, Math.PI * 2);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.restore();

      // 4. Onda sonora reativa radial (Ouvindo e Falando) ou pulso calmo (Ocioso)
      const wavePoints = 72;
      const baseR = 92;
      ctx.beginPath();
      for (let i = 0; i <= wavePoints; i++) {
        const a = (i / wavePoints) * Math.PI * 2;
        let disp = 0;
        if (mode === "listening") {
          const amp = 7 + coreAnim.energy * 18;
          disp =
            Math.sin(a * 6 + coreAnim.t * 4.2) * amp * 0.65 +
            Math.cos(a * 11 - coreAnim.t * 6.0) * amp * 0.35;
        } else if (mode === "speaking") {
          const amp = 6 + coreAnim.energy * 16;
          disp =
            Math.sin(a * 8 - coreAnim.t * 5.2) * amp * 0.6 +
            Math.sin(a * 4 + coreAnim.t * 3.1) * amp * 0.4;
        } else if (mode === "processing") {
          disp = Math.sin(a * 3 + coreAnim.t * 7.0) * 5;
        } else {
          disp = Math.sin(coreAnim.t * 1.5) * 3.2;
        }
        const r = baseR + disp;
        const x = cx + Math.cos(a) * r;
        const y = cy + Math.sin(a) * r;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.closePath();
      ctx.strokeStyle =
        mode === "speaking"
          ? "rgba(238, 244, 255, 0.9)"
          : `rgba(0, 229, 255, ${0.58 + coreAnim.energy * 0.35})`;
      ctx.lineWidth = mode === "idle" ? 2.5 : 3.5;
      ctx.stroke();

      // 5. Ondas expansivas quando ouvindo ou falando
      if (mode === "listening" || mode === "speaking") {
        const rippleProgress = (coreAnim.t * 0.45) % 1;
        const rippleR = 96 + rippleProgress * 92;
        ctx.strokeStyle = `rgba(0, 229, 255, ${(1 - rippleProgress) * 0.38})`;
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.arc(cx, cy, rippleR, 0, Math.PI * 2);
        ctx.stroke();
      }

      requestAnimationFrame(frame);
    }

    requestAnimationFrame(frame);
  }

  // ------------------------------------------------------------------------
  // Sistema de Voz: TTS (window.speechSynthesis pt-BR com chunking)
  // ------------------------------------------------------------------------
  function pickBestPtBrVoice() {
    if (!("speechSynthesis" in window)) return null;
    const voices = window.speechSynthesis.getVoices() || [];
    const normalizeLang = (lang) => (lang || "").toLowerCase().replace("_", "-");
    const normalizeName = (name) =>
      (name || "")
        .normalize("NFD")
        .replace(/[\u0300-\u036f]/g, "")
        .toLowerCase();

    const ptRegional = voices.filter((v) => {
      const l = normalizeLang(v.lang);
      return l.startsWith("pt-br") || l.startsWith("pt-pt");
    });
    const pool = ptRegional.length
      ? ptRegional
      : voices.filter((v) => normalizeLang(v.lang).startsWith("pt"));

    if (!pool.length) return null;

    const malePatterns = [
      /\bdaniel\b/,
      /\bfelipe\b/,
      /\bantonio\b/,
      /\bricardo\b/,
      /\bfabio\b/,
      /\bhumberto\b/,
      /\bnicolau\b/,
      /\bduarte\b/,
      /\bjulio\b/,
      /\bdonato\b/,
      /\bvalerio\b/,
      /\btiago\b/,
      /\bpedro\b/,
      /\bcarlos\b/,
      /\blucas\b/,
      /\bmale\b/,
      /\bmasculin[oa]\b/,
      /\bhomem\b/,
      /pt-br-x-ptd/,
      /pt-br-x-pte/,
    ];

    const femalePatterns = [
      /\bluciana\b/,
      /\bfrancisca\b/,
      /\bmaria\b/,
      /\bfernanda\b/,
      /\bvitoria\b/,
      /\braquel\b/,
      /\bthalita\b/,
      /\bbrenda\b/,
      /\belza\b/,
      /\bgiovanna\b/,
      /\bleila\b/,
      /\bleticia\b/,
      /\bmanuela\b/,
      /\byara\b/,
      /\bines\b/,
      /\bjoana\b/,
      /\bhelena\b/,
      /\bfemale\b/,
      /\bfeminin[oa]\b/,
      /\bmulher\b/,
      /pt-br-x-afs/,
    ];

    // Prioriza vozes masculinas em pt-BR/pt-PT mantendo fallback para qualquer voz em português
    const ranked = [...pool].sort((a, b) => {
      const score = (v) => {
        const l = normalizeLang(v.lang);
        const n = normalizeName(v.name);
        const uri = normalizeName(v.voiceURI);
        const haystack = `${n} ${uri}`;
        let s = 0;

        const isMale = malePatterns.some((re) => re.test(haystack));
        const isFemale = !isMale && femalePatterns.some((re) => re.test(haystack));

        if (isMale) s += 100;
        if (isFemale) s -= 30;
        if (l.startsWith("pt-br")) s += 25;
        else if (l.startsWith("pt-pt")) s += 15;
        if (haystack.includes("neural") || haystack.includes("natural") || haystack.includes("online")) s += 20;
        if (haystack.includes("google") && haystack.includes("portugu")) s += 12;
        if (v.localService) s += 4;
        return s;
      };
      return score(b) - score(a);
    });

    return ranked[0];
  }

  function refreshVoices() {
    state.selectedVoice = pickBestPtBrVoice();
    if (state.selectedVoice) {
      el.voiceNameTag.textContent = state.selectedVoice.name.slice(0, 24);
    } else {
      el.voiceNameTag.textContent = "TTS pt-BR padrão";
    }
  }

  function stripMarkdownForSpeech(markdown) {
    let text = String(markdown || "");
    text = text.replace(/```[\s\S]*?```/g, " Código exibido na tela. ");
    text = text.replace(/`([^`]+)`/g, "$1");
    text = text.replace(/!\[([^\]]*)\]\([^)]+\)/g, "");
    text = text.replace(/\[([^\]]+)\]\([^)]+\)/g, "$1");
    text = text.replace(/^\s{0,3}#{1,6}\s+/gm, "");
    text = text.replace(/[*_~>]/g, "");
    text = text.replace(/\|/g, ", ");
    text = text.replace(/^\s*[-+•]\s+/gm, "");
    text = text.replace(/\n{2,}/g, ". ");
    text = text.replace(/\n/g, " ");
    text = text.replace(/\s{2,}/g, " ").trim();
    return text;
  }

  function chunkTextForAndroidTTS(text, maxLen = 190) {
    const sentences = text.match(/[^.!?]+[.!?]*\s*/g) || [text];
    const chunks = [];
    let current = "";
    for (const s of sentences) {
      const clean = s.trim();
      if (!clean) continue;
      if ((current + " " + clean).trim().length <= maxLen) {
        current = (current + " " + clean).trim();
      } else {
        if (current) chunks.push(current);
        current = clean;
      }
    }
    if (current) chunks.push(current);
    return chunks;
  }

  function stopSpeaking() {
    state.speechQueue = [];
    state.isSpeaking = false;
    if ("speechSynthesis" in window) {
      window.speechSynthesis.cancel();
    }
    if (state.coreStatus === "speaking") {
      setCoreState("idle");
    }
  }

  function speakText(markdownText, { autoResumeHandsFree = true } = {}) {
    if (state.muted || !("speechSynthesis" in window)) {
      if (autoResumeHandsFree && state.handsFree && !state.isListening) {
        setTimeout(() => startListening(), 450);
      }
      return;
    }

    stopSpeaking();

    const clean = stripMarkdownForSpeech(markdownText);
    if (!clean) return;

    const chunks = chunkTextForAndroidTTS(clean);
    if (!chunks.length) return;

    state.speechQueue = chunks;
    state.isSpeaking = true;
    setCoreState("speaking", "Falando resposta (toque para interromper)");

    const speakNext = () => {
      if (!state.isSpeaking || !state.speechQueue.length) {
        state.isSpeaking = false;
        if (state.coreStatus === "speaking") {
          setCoreState("idle");
        }
        if (autoResumeHandsFree && state.handsFree && !state.isSending && !state.isListening) {
          setTimeout(() => startListening(), 500);
        }
        return;
      }

      const segment = state.speechQueue.shift();
      const utter = new SpeechSynthesisUtterance(segment);
      utter.lang = "pt-BR";
      utter.rate = state.ttsRate;
      utter.pitch = 1.0;
      if (state.selectedVoice) {
        utter.voice = state.selectedVoice;
      }

      utter.onend = () => speakNext();
      utter.onerror = () => {
        state.isSpeaking = false;
        state.speechQueue = [];
        if (state.coreStatus === "speaking") setCoreState("idle");
      };

      window.speechSynthesis.speak(utter);
    };

    speakNext();
  }

  function syncVoiceControlsUI() {
    el.muteBtnTop.classList.toggle("active", state.muted);
    el.muteBtnTop.querySelector(".icon-sound-on").classList.toggle("hidden", state.muted);
    el.muteBtnTop.querySelector(".icon-sound-off").classList.toggle("hidden", !state.muted);

    el.muteBtnPanel.classList.toggle("is-muted", state.muted);
    el.muteBtnPanel.setAttribute("aria-pressed", String(!state.muted));
    el.muteLabel.textContent = state.muted ? "Silencioso" : "Voz Ativa";

    el.handsfreeBtn.setAttribute("aria-pressed", String(state.handsFree));
    el.ttsRateSelect.value = String(state.ttsRate);
    if (!el.ttsRateSelect.value) el.ttsRateSelect.value = "1.12";
  }

  function toggleMute() {
    state.muted = !state.muted;
    localStorage.setItem(STORAGE.MUTED, String(state.muted));
    if (state.muted) stopSpeaking();
    syncVoiceControlsUI();
    showToast(state.muted ? "Modo silencioso ativado." : "Áudio de voz ativado.");
  }

  function toggleHandsFree() {
    state.handsFree = !state.handsFree;
    localStorage.setItem(STORAGE.HANDSFREE, String(state.handsFree));
    syncVoiceControlsUI();
    if (state.handsFree) {
      showToast("Modo contínuo ativado.");
      if (state.coreStatus === "idle") startListening();
    } else {
      showToast("Modo contínuo desativado.");
      if (state.isListening) stopListening();
    }
  }

  // ------------------------------------------------------------------------
  // Sistema de Voz: STT (Web Speech API pt-BR + Analyser reativo)
  // ------------------------------------------------------------------------
  async function startMicMeter() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) return;
    try {
      state.micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      state.audioCtx = new AudioCtx();
      const source = state.audioCtx.createMediaStreamSource(state.micStream);
      state.analyser = state.audioCtx.createAnalyser();
      state.analyser.fftSize = 128;
      source.connect(state.analyser);
    } catch (_err) {
      // Sem permissão de analyser não impede a Web Speech API de funcionar
    }
  }

  function stopMicMeter() {
    if (state.micStream) {
      state.micStream.getTracks().forEach((t) => t.stop());
      state.micStream = null;
    }
    if (state.audioCtx) {
      state.audioCtx.close().catch(() => {});
      state.audioCtx = null;
    }
    state.analyser = null;
    state.micLevel = 0;
  }

  function startListening() {
    const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRec) {
      showToast("Reconhecimento de voz não suportado neste navegador. Use Chrome no Android.", 3800);
      return;
    }

    if (state.isSending) return;

    // Interrompe fala imediatamente (barge-in)
    if (state.isSpeaking) {
      stopSpeaking();
    }

    if (state.isListening) {
      stopListening();
      return;
    }

    let finalTranscript = "";
    let interimTranscript = "";

    const recognition = new SpeechRec();
    recognition.lang = "pt-BR";
    recognition.interimResults = true;
    recognition.continuous = false;
    recognition.maxAlternatives = 1;

    state.recognition = recognition;
    state.isListening = true;
    setCoreState("listening", "Pode falar, senhor...");
    startMicMeter();

    recognition.onresult = (event) => {
      interimTranscript = "";
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const res = event.results[i];
        if (res.isFinal) {
          finalTranscript += res[0].transcript + " ";
        } else {
          interimTranscript += res[0].transcript;
        }
      }
      const preview = (finalTranscript + interimTranscript).trim();
      if (preview) {
        el.coreSubstatus.textContent = `"${preview}"`;
      }
    };

    recognition.onerror = (event) => {
      stopMicMeter();
      state.isListening = false;
      state.recognition = null;
      if (event.error === "not-allowed" || event.error === "service-not-allowed") {
        showToast("Permissão de microfone negada no navegador.", 3500);
        state.handsFree = false;
        localStorage.setItem(STORAGE.HANDSFREE, "false");
        syncVoiceControlsUI();
      } else if (event.error !== "no-speech" && event.error !== "aborted") {
        showToast(`Erro no microfone: ${event.error}`);
      }
      if (state.coreStatus === "listening") setCoreState("idle");
    };

    recognition.onend = () => {
      stopMicMeter();
      state.isListening = false;
      state.recognition = null;

      const spoken = (finalTranscript || interimTranscript).trim();
      if (spoken) {
        sendChatMessage(spoken, true);
      } else {
        if (state.coreStatus === "listening") setCoreState("idle");
        if (state.handsFree && !state.isSending && !state.isSpeaking) {
          setTimeout(() => {
            if (state.handsFree && !state.isListening && !state.isSending && !state.isSpeaking) {
              startListening();
            }
          }, 900);
        }
      }
    };

    try {
      recognition.start();
    } catch (_err) {
      stopMicMeter();
      state.isListening = false;
      setCoreState("idle");
    }
  }

  function stopListening() {
    if (state.recognition) {
      try {
        state.recognition.abort();
      } catch (_e) {}
      state.recognition = null;
    }
    state.isListening = false;
    stopMicMeter();
    if (state.coreStatus === "listening") {
      setCoreState("idle");
    }
  }

  // ------------------------------------------------------------------------
  // Renderizador de Markdown seguro (negrito, listas, tabelas e blocos código)
  // ------------------------------------------------------------------------
  function renderInlineMarkdown(text) {
    let out = escapeHtml(text);

    // Inline code protegido com placeholders
    const codeTokens = [];
    out = out.replace(/`([^`]+)`/g, (_m, code) => {
      const idx = codeTokens.length;
      codeTokens.push(`<code>${code}</code>`);
      return `\u0000CODE${idx}\u0000`;
    });

    // Links seguros http(s)
    out = out.replace(
      /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
      '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>'
    );

    // Negrito, itálico, riscado
    out = out.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    out = out.replace(/__([^_]+)__/g, "<strong>$1</strong>");
    out = out.replace(/~~([^~]+)~~/g, "<del>$1</del>");
    out = out.replace(/(?<!\*)\*([^*\n]+)\*(?!\*)/g, "<em>$1</em>");

    // Restaura inline code
    out = out.replace(/\u0000CODE(\d+)\u0000/g, (_m, idx) => codeTokens[Number(idx)]);
    return out;
  }

  function renderMarkdown(raw) {
    const src = String(raw || "").replace(/\r\n/g, "\n");
    const blocks = [];
    let codeIndex = 0;

    // Extrai blocos de código cercados (```lang ... ```)
    const replaced = src.replace(/```([a-zA-Z0-9_-]*)\n([\s\S]*?)```/g, (_m, lang, code) => {
      const token = `\u0001BLOCK${codeIndex++}\u0001`;
      const label = escapeHtml(lang || "código");
      const escapedCode = escapeHtml(code.replace(/\n$/, ""));
      blocks.push({
        token,
        html:
          `<div class="code-block-wrap">` +
          `<div class="code-block-header"><span>${label}</span>` +
          `<button type="button" class="copy-code-btn" data-copy-code="1">Copiar</button></div>` +
          `<pre><code>${escapedCode}</code></pre></div>`,
      });
      return `\n${token}\n`;
    });

    const lines = replaced.split("\n");
    const htmlParts = [];
    let i = 0;

    const isTableSep = (line) => /^\s*\|?(\s*:?-{3,}:?\s*\|)+\s*:?-{3,}:?\s*\|?\s*$/.test(line);

    while (i < lines.length) {
      const line = lines[i];
      const trimmed = line.trim();

      if (!trimmed) {
        i++;
        continue;
      }

      // Token de bloco de código
      const blockMatch = blocks.find((b) => b.token === trimmed);
      if (blockMatch) {
        htmlParts.push(blockMatch.html);
        i++;
        continue;
      }

      // Cabeçalhos
      const hMatch = trimmed.match(/^(#{1,4})\s+(.+)$/);
      if (hMatch) {
        const level = hMatch[1].length;
        htmlParts.push(`<h${level}>${renderInlineMarkdown(hMatch[2])}</h${level}>`);
        i++;
        continue;
      }

      // Linha horizontal
      if (/^(-{3,}|\*{3,}|_{3,})$/.test(trimmed)) {
        htmlParts.push("<hr>");
        i++;
        continue;
      }

      // Tabela GFM
      if (trimmed.includes("|") && i + 1 < lines.length && isTableSep(lines[i + 1])) {
        const parseRow = (rowStr) =>
          rowStr
            .trim()
            .replace(/^\|/, "")
            .replace(/\|$/, "")
            .split("|")
            .map((c) => c.trim());

        const headers = parseRow(line);
        i += 2;
        const rows = [];
        while (i < lines.length && lines[i].trim().includes("|") && lines[i].trim() !== "") {
          rows.push(parseRow(lines[i]));
          i++;
        }

        const thead = `<thead><tr>${headers.map((h) => `<th>${renderInlineMarkdown(h)}</th>`).join("")}</tr></thead>`;
        const tbody = `<tbody>${rows
          .map((r) => `<tr>${headers.map((_h, idx) => `<td>${renderInlineMarkdown(r[idx] || "")}</td>`).join("")}</tr>`)
          .join("")}</tbody>`;
        htmlParts.push(`<div class="table-scroll"><table>${thead}${tbody}</table></div>`);
        continue;
      }

      // Blockquote
      if (trimmed.startsWith(">")) {
        const quoteLines = [];
        while (i < lines.length && lines[i].trim().startsWith(">")) {
          quoteLines.push(lines[i].trim().replace(/^>\s?/, ""));
          i++;
        }
        htmlParts.push(`<blockquote>${quoteLines.map(renderInlineMarkdown).join("<br>")}</blockquote>`);
        continue;
      }

      // Lista não ordenada
      if (/^[-*+]\s+/.test(trimmed)) {
        const items = [];
        while (i < lines.length && /^\s*[-*+]\s+/.test(lines[i])) {
          items.push(lines[i].trim().replace(/^[-*+]\s+/, ""));
          i++;
        }
        htmlParts.push(`<ul>${items.map((it) => `<li>${renderInlineMarkdown(it)}</li>`).join("")}</ul>`);
        continue;
      }

      // Lista ordenada
      if (/^\d+\.\s+/.test(trimmed)) {
        const items = [];
        while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i])) {
          items.push(lines[i].trim().replace(/^\d+\.\s+/, ""));
          i++;
        }
        htmlParts.push(`<ol>${items.map((it) => `<li>${renderInlineMarkdown(it)}</li>`).join("")}</ol>`);
        continue;
      }

      // Parágrafo normal
      const paraLines = [];
      while (
        i < lines.length &&
        lines[i].trim() !== "" &&
        !lines[i].trim().startsWith("#") &&
        !lines[i].trim().startsWith(">") &&
        !/^\s*[-*+]\s+/.test(lines[i]) &&
        !/^\s*\d+\.\s+/.test(lines[i]) &&
        !blocks.some((b) => b.token === lines[i].trim())
      ) {
        paraLines.push(lines[i]);
        i++;
      }
      htmlParts.push(`<p>${paraLines.map(renderInlineMarkdown).join("<br>")}</p>`);
    }

    return htmlParts.join("");
  }

  // ------------------------------------------------------------------------
  // Renderização de mensagens no chat
  // ------------------------------------------------------------------------
  function renderWelcomeState() {
    el.messagesList.innerHTML = `
      <div class="empty-welcome">
        <h2>À sua disposição, senhor.</h2>
        <p>Toque no núcleo central para falar, digite abaixo ou anexe um PDF/foto para análise imediata.</p>
        <div class="welcome-prompts">
          <button type="button" class="welcome-chip" data-prompt="Faça um resumo do meu dia e verifique minhas tarefas pendentes.">Resumo do dia</button>
          <button type="button" class="welcome-chip" data-prompt="Que horas são agora em Brasília?">Data e hora</button>
          <button type="button" class="welcome-chip" data-prompt="Salve na minha memória que prefiro respostas objetivas e estratégicas.">Salvar preferência</button>
          <button type="button" class="welcome-chip" data-prompt="Adicione uma tarefa de prioridade alta: Revisar plano semanal até sexta-feira.">Criar tarefa</button>
        </div>
      </div>
    `;
  }

  function createMessageElement(msg) {
    const row = document.createElement("article");
    row.className = `message-row ${msg.role}`;

    const sender = msg.role === "assistant" ? "J.A.R.V.I.S." : "Você";
    const timeStr = formatTimeShort(msg.created_at);

    let toolsHtml = "";
    if (msg.role === "assistant" && Array.isArray(msg.tool_calls) && msg.tool_calls.length) {
      const chips = msg.tool_calls
        .map(
          (t) =>
            `<span class="tool-chip ${t.success === false ? "failed" : ""}">⚡ ${escapeHtml(
              t.label || t.name
            )}</span>`
        )
        .join("");
      toolsHtml = `<div class="tool-chips">${chips}</div>`;
    }

    let attachHtml = "";
    if (msg.attachment_name) {
      attachHtml = `<div class="attachment-tag">📎 ${escapeHtml(msg.attachment_name)}</div>`;
    }

    const bodyHtml =
      msg.role === "assistant"
        ? `<div class="markdown-body">${renderMarkdown(msg.content)}</div>`
        : `<div class="markdown-body"><p>${escapeHtml(msg.content).replace(/\n/g, "<br>")}</p></div>`;

    const speakBtnHtml =
      msg.role === "assistant"
        ? `<button type="button" class="speak-again-btn" data-speak-msg="1" title="Ouvir resposta novamente">🔊 Ouvir</button>`
        : "";

    row.innerHTML = `
      <div class="message-meta">
        <span class="message-sender">${sender}</span>
        ${msg.voice_mode ? "<span>• voz</span>" : ""}
        ${timeStr ? `<span>${timeStr}</span>` : ""}
      </div>
      <div class="message-bubble">
        ${attachHtml}
        ${toolsHtml}
        ${bodyHtml}
      </div>
      ${speakBtnHtml}
    `;

    if (msg.role === "assistant") {
      row.dataset.rawContent = msg.content;
    }

    return row;
  }

  function appendMessage(msg) {
    const empty = el.messagesList.querySelector(".empty-welcome");
    if (empty) empty.remove();
    el.messagesList.appendChild(createMessageElement(msg));
    scrollChatToBottom();
  }

  function appendTypingIndicator() {
    const empty = el.messagesList.querySelector(".empty-welcome");
    if (empty) empty.remove();
    const row = document.createElement("article");
    row.id = "typing-indicator";
    row.className = "message-row assistant";
    row.innerHTML = `
      <div class="message-meta"><span class="message-sender">J.A.R.V.I.S.</span></div>
      <div class="message-bubble">
        <div class="typing-dots"><span></span><span></span><span></span></div>
      </div>
    `;
    el.messagesList.appendChild(row);
    scrollChatToBottom();
    return row;
  }

  function scrollChatToBottom() {
    el.messagesList.scrollTop = el.messagesList.scrollHeight;
  }

  // ------------------------------------------------------------------------
  // Anexos multimodais (PDF, imagens, texto)
  // ------------------------------------------------------------------------
  function clearAttachment() {
    state.pendingFile = null;
    if (state.pendingThumbUrl) {
      URL.revokeObjectURL(state.pendingThumbUrl);
      state.pendingThumbUrl = null;
    }
    el.fileInput.value = "";
    el.attachmentBar.classList.add("hidden");
    el.attachmentThumb.classList.add("hidden");
    el.attachmentFileBadge.classList.add("hidden");
  }

  function setAttachment(file) {
    if (!file) return;
    if (file.size > 20 * 1024 * 1024) {
      showToast("Arquivo muito grande. Limite máximo: 20 MB.", 3200);
      return;
    }
    clearAttachment();
    state.pendingFile = file;
    el.attachmentName.textContent = file.name;
    el.attachmentSize.textContent = formatBytes(file.size);

    if (file.type && file.type.startsWith("image/")) {
      state.pendingThumbUrl = URL.createObjectURL(file);
      el.attachmentThumb.src = state.pendingThumbUrl;
      el.attachmentThumb.classList.remove("hidden");
    } else {
      const ext = (file.name.split(".").pop() || "DOC").toUpperCase().slice(0, 4);
      el.attachmentFileBadge.textContent = ext;
      el.attachmentFileBadge.classList.remove("hidden");
    }

    el.attachmentBar.classList.remove("hidden");
    el.messageInput.focus();
  }

  // ------------------------------------------------------------------------
  // Envio de mensagens (Texto / Voz / Multimodal)
  // ------------------------------------------------------------------------
  async function sendChatMessage(text, isVoiceMode = false) {
    const trimmed = (text || "").trim();
    const file = state.pendingFile;

    if (!trimmed && !file) return;
    if (state.isSending) return;

    stopSpeaking();
    state.isSending = true;
    el.sendBtn.disabled = true;
    setCoreState("processing", file ? `Analisando ${file.name}...` : "Processando solicitação...");

    const optimisticUserMsg = {
      role: "user",
      content: trimmed || `Analise o arquivo anexado: ${file.name}`,
      attachment_name: file ? file.name : null,
      voice_mode: isVoiceMode,
      created_at: new Date().toISOString(),
    };
    appendMessage(optimisticUserMsg);

    let requestOptions;
    if (file) {
      const formData = new FormData();
      formData.append("message", trimmed);
      formData.append("voice_mode", String(Boolean(isVoiceMode)));
      formData.append("session_id", "default");
      formData.append("model", state.selectedModel);
      formData.append("file", file, file.name);
      requestOptions = {
        method: "POST",
        body: formData,
      };
    } else {
      requestOptions = {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: trimmed,
          voice_mode: Boolean(isVoiceMode),
          session_id: "default",
          model: state.selectedModel,
        }),
      };
    }

    el.messageInput.value = "";
    autoResizeTextarea();
    clearAttachment();

    const typingNode = appendTypingIndicator();

    try {
      const data = await apiFetch("/api/chat", requestOptions);

      typingNode.remove();

      const assistantMsg = data.assistant_message || {
        role: "assistant",
        content: data.reply,
        tool_calls: data.tools_used || [],
        voice_mode: isVoiceMode,
        created_at: new Date().toISOString(),
      };
      appendMessage(assistantMsg);

      if (data.stats) updateStatsUI(data.stats);
      if (data.tools_used && data.tools_used.length) {
        refreshDrawerData();
      }

      setCoreState("idle");

      // Fala em voz alta automaticamente se veio por voz ou se áudio não está mudo
      if (isVoiceMode || !state.muted) {
        speakText(assistantMsg.content, { autoResumeHandsFree: isVoiceMode || state.handsFree });
      }
    } catch (err) {
      typingNode.remove();
      setCoreState("idle");
      appendMessage({
        role: "assistant",
        content: `**Aviso do sistema:** ${err.message || "Falha ao processar solicitação."}`,
        created_at: new Date().toISOString(),
      });
    } finally {
      state.isSending = false;
      el.sendBtn.disabled = false;
    }
  }

  // ------------------------------------------------------------------------
  // Status, Estatísticas e Dados Persistentes (Drawer)
  // ------------------------------------------------------------------------
  function syncModelUI() {
    if (!ALLOWED_MODELS.includes(state.selectedModel)) {
      state.selectedModel = DEFAULT_MODEL;
    }
    if (el.modelSelect) el.modelSelect.value = state.selectedModel;
    if (el.modelTag) el.modelTag.textContent = state.selectedModel;
  }

  function applyServerStatus(data) {
    if (!getStoredModel() && data.model && ALLOWED_MODELS.includes(data.model)) {
      state.selectedModel = data.model;
    }
    syncModelUI();
    const ok = Boolean(data.api_key_configured);
    el.apiWarningChip.classList.toggle("hidden", ok);
    el.connectionDot.classList.toggle("warn", !ok);
    if (data.stats) updateStatsUI(data.stats);
  }

  function updateStatsUI(stats) {
    const p = stats.tarefas_pendentes || 0;
    const n = stats.notas || 0;
    const m = stats.memorias || 0;

    el.pendingBadge.textContent = String(p);
    el.pendingBadge.classList.toggle("hidden", p === 0);

    el.statTasksSub.textContent = `${p} ${p === 1 ? "pendente" : "pendentes"}`;
    el.statNotesSub.textContent = `${n} ${n === 1 ? "anotação" : "anotações"}`;
    el.statMemoriesSub.textContent = `${m} ${m === 1 ? "registro" : "registros"}`;
  }

  function updateGoogleAuthUI() {
    if (!el.googleAuthBtn || !el.googleAuthLabel) return;
    const connected = Boolean(state.googleAuth.connected);
    el.googleAuthBtn.classList.toggle("connected", connected);
    el.googleAuthLabel.textContent = connected ? "Google Conectado" : "Conectar Google";
    if (connected) {
      const account = state.googleAuth.email ? ` (${state.googleAuth.email})` : "";
      el.googleAuthBtn.title = `Google Conectado${account} — clique para reconectar ou atualizar permissões`;
      el.googleAuthBtn.setAttribute("aria-label", `Google Conectado${account}`);
    } else if (state.googleAuth.configured) {
      el.googleAuthBtn.title = "Conectar conta Google (Agenda, Gmail, Drive e Tarefas)";
      el.googleAuthBtn.setAttribute("aria-label", "Conectar conta Google");
    } else {
      el.googleAuthBtn.title = "Configure GOOGLE_CLIENT_ID e GOOGLE_CLIENT_SECRET no servidor para conectar";
      el.googleAuthBtn.setAttribute("aria-label", "Conectar conta Google");
    }
  }

  async function refreshGoogleAuthStatus() {
    try {
      const resp = await fetch("/auth/status", { cache: "no-store" });
      if (!resp.ok) return;
      const data = await resp.json();
      state.googleAuth = {
        connected: Boolean(data.connected),
        configured: Boolean(data.configured),
        email: data.email || null,
      };
      updateGoogleAuthUI();
    } catch (_err) {
      // Silencioso em verificação de fundo
    }
  }

  function handleGoogleAuthCallbackParams() {
    const params = new URLSearchParams(window.location.search);
    const result = params.get("google_auth");
    if (!result) return;
    const reason = params.get("reason") || "";
    if (result === "success") {
      showToast("Conta Google conectada com sucesso!", 3600);
    } else if (result === "error") {
      showToast(
        reason ? `Falha ao conectar Google: ${reason}` : "Falha ao conectar conta Google.",
        4200
      );
    }
    params.delete("google_auth");
    params.delete("reason");
    const cleanQuery = params.toString();
    const cleanUrl = `${window.location.pathname}${cleanQuery ? `?${cleanQuery}` : ""}${window.location.hash}`;
    window.history.replaceState({}, document.title, cleanUrl);
  }

  async function loadInitialData() {
    try {
      const [hist] = await Promise.all([
        apiFetch("/api/history?limit=40"),
        refreshDrawerData(),
        refreshGoogleAuthStatus(),
      ]);

      el.messagesList.innerHTML = "";
      if (hist.messages && hist.messages.length) {
        hist.messages.forEach((m) => el.messagesList.appendChild(createMessageElement(m)));
        scrollChatToBottom();
      } else {
        renderWelcomeState();
      }
    } catch (err) {
      showToast(`Erro ao carregar dados: ${err.message}`);
    }
  }

  async function refreshDrawerData() {
    try {
      const [tasksRes, memRes, notesRes] = await Promise.all([
        apiFetch("/api/tasks?status=todas"),
        apiFetch(`/api/memories?termo=${encodeURIComponent(el.memorySearchInput.value || "")}`),
        apiFetch("/api/notes"),
      ]);
      renderTasksList(tasksRes.tasks || []);
      renderMemoriesList(memRes.memories || []);
      renderNotesList(notesRes.notes || []);
      if (tasksRes.stats) updateStatsUI(tasksRes.stats);
    } catch (_err) {
      // Silencioso em refresh de fundo
    }
  }

  function renderTasksList(tasks) {
    if (!tasks.length) {
      el.tasksList.innerHTML = `<p class="empty-list">Nenhuma tarefa registrada ainda.</p>`;
      return;
    }

    el.tasksList.innerHTML = tasks
      .map((t) => {
        const done = t.status === "concluida";
        return `
          <div class="record-item ${done ? "done" : ""}" data-task-id="${t.id}">
            <button type="button" class="task-check-btn" data-toggle-task="${t.id}" aria-label="Alternar conclusão">
              ✓
            </button>
            <div class="record-main">
              <p class="record-title">${escapeHtml(t.titulo)}</p>
              <div class="record-meta">
                <span class="meta-pill prio-${escapeHtml(t.prioridade)}">${escapeHtml(t.prioridade)}</span>
                ${t.prazo ? `<span class="meta-pill">⏱ ${escapeHtml(t.prazo)}</span>` : ""}
                <span class="meta-pill">#${t.id}</span>
              </div>
            </div>
            <button type="button" class="record-del-btn" data-del-task="${t.id}" aria-label="Excluir tarefa">✕</button>
          </div>
        `;
      })
      .join("");
  }

  function renderMemoriesList(memories) {
    if (!memories.length) {
      el.memoriesList.innerHTML = `<p class="empty-list">Nenhuma memória encontrada.</p>`;
      return;
    }

    el.memoriesList.innerHTML = memories
      .map(
        (m) => `
        <div class="record-item">
          <div class="record-main">
            <p class="record-title">${escapeHtml(m.chave)}</p>
            <p class="record-body">${escapeHtml(m.valor)}</p>
            <div class="record-meta">
              <span class="meta-pill">${escapeHtml(m.categoria)}</span>
            </div>
          </div>
          <button type="button" class="record-del-btn" data-del-memory="${m.id}" aria-label="Excluir memória">✕</button>
        </div>
      `
      )
      .join("");
  }

  function renderNotesList(notes) {
    if (!notes.length) {
      el.notesList.innerHTML = `<p class="empty-list">Nenhuma nota salva ainda.</p>`;
      return;
    }

    el.notesList.innerHTML = notes
      .map(
        (n) => `
        <div class="record-item">
          <div class="record-main">
            <p class="record-title">${escapeHtml(n.titulo)}</p>
            <p class="record-body">${escapeHtml(n.conteudo)}</p>
            <div class="record-meta">
              <span class="meta-pill">#${escapeHtml(n.tag)}</span>
              <span class="meta-pill">${formatTimeShort(n.updated_at)}</span>
            </div>
          </div>
          <button type="button" class="record-del-btn" data-del-note="${n.id}" aria-label="Excluir nota">✕</button>
        </div>
      `
      )
      .join("");
  }

  // ------------------------------------------------------------------------
  // Controle da Gaveta Lateral (Drawer)
  // ------------------------------------------------------------------------
  function setDrawerTab(tabName) {
    state.activeDrawerTab = tabName;
    el.drawerTabs.forEach((btn) => {
      const active = btn.dataset.tab === tabName;
      btn.classList.toggle("active", active);
      btn.setAttribute("aria-selected", String(active));
    });
    Object.entries(el.tabPanels).forEach(([name, panel]) => {
      panel.classList.toggle("active", name === tabName);
    });
  }

  function openDrawer(tabName) {
    if (tabName) setDrawerTab(tabName);
    el.drawerBackdrop.classList.remove("hidden");
    el.hudDrawer.classList.add("open");
    el.hudDrawer.setAttribute("aria-hidden", "false");
    refreshDrawerData();
  }

  function closeDrawer() {
    el.hudDrawer.classList.remove("open");
    el.hudDrawer.setAttribute("aria-hidden", "true");
    el.drawerBackdrop.classList.add("hidden");
  }

  // ------------------------------------------------------------------------
  // Auto-resize da textarea e eventos gerais
  // ------------------------------------------------------------------------
  function autoResizeTextarea() {
    el.messageInput.style.height = "auto";
    el.messageInput.style.height = `${Math.min(el.messageInput.scrollHeight, 140)}px`;
  }

  function bindEvents() {
    // Núcleo de voz & microfone
    el.coreButton.addEventListener("click", () => {
      if (state.coreStatus === "speaking") {
        stopSpeaking();
        startListening();
      } else if (state.coreStatus === "listening") {
        stopListening();
      } else {
        startListening();
      }
    });

    el.composerMicBtn.addEventListener("click", () => {
      if (state.isListening) stopListening();
      else startListening();
    });

    el.interruptSpeechBtn.addEventListener("click", () => {
      stopSpeaking();
      showToast("Fala interrompida.");
    });

    el.muteBtnTop.addEventListener("click", toggleMute);
    el.muteBtnPanel.addEventListener("click", toggleMute);
    el.handsfreeBtn.addEventListener("click", toggleHandsFree);

    el.ttsRateSelect.addEventListener("change", () => {
      state.ttsRate = parseFloat(el.ttsRateSelect.value) || 1.12;
      localStorage.setItem(STORAGE.RATE, String(state.ttsRate));
      showToast(`Velocidade da voz: ${state.ttsRate}x`);
    });

    if (el.modelSelect) {
      el.modelSelect.addEventListener("change", () => {
        const chosen = el.modelSelect.value;
        if (!ALLOWED_MODELS.includes(chosen)) return;
        state.selectedModel = chosen;
        localStorage.setItem(STORAGE.MODEL, chosen);
        syncModelUI();
        const label = el.modelSelect.options[el.modelSelect.selectedIndex]?.textContent || chosen;
        showToast(`Modelo ativo: ${label}`);
      });
    }

    if (el.googleAuthBtn) {
      el.googleAuthBtn.addEventListener("click", () => {
        if (!state.googleAuth.configured && !state.googleAuth.connected) {
          showToast(
            "Configure GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET e GOOGLE_REDIRECT_URI no servidor.",
            4200
          );
          return;
        }
        if (state.googleAuth.connected) {
          const account = state.googleAuth.email ? ` (${state.googleAuth.email})` : "";
          const reconnect = confirm(
            `Sua conta Google${account} já está conectada. Deseja reconectar ou atualizar as permissões?`
          );
          if (!reconnect) return;
        }
        window.location.href = "/auth/google";
      });
    }

    // Atalhos rápidos & chips de boas-vindas
    document.addEventListener("click", (e) => {
      const promptBtn = e.target.closest("[data-prompt]");
      if (promptBtn) {
        sendChatMessage(promptBtn.dataset.prompt, false);
        return;
      }

      const tabBtn = e.target.closest("[data-open-tab]");
      if (tabBtn) {
        openDrawer(tabBtn.dataset.openTab);
        return;
      }

      const copyBtn = e.target.closest("[data-copy-code]");
      if (copyBtn) {
        const codeEl = copyBtn.closest(".code-block-wrap")?.querySelector("pre code");
        if (codeEl && navigator.clipboard) {
          navigator.clipboard.writeText(codeEl.textContent || "");
          copyBtn.textContent = "Copiado!";
          setTimeout(() => (copyBtn.textContent = "Copiar"), 1600);
        }
        return;
      }

      const speakBtn = e.target.closest("[data-speak-msg]");
      if (speakBtn) {
        const row = speakBtn.closest(".message-row");
        if (row && row.dataset.rawContent) {
          if (state.muted) {
            state.muted = false;
            localStorage.setItem(STORAGE.MUTED, "false");
            syncVoiceControlsUI();
          }
          speakText(row.dataset.rawContent, { autoResumeHandsFree: false });
        }
      }
    });

    // Formulário de chat
    el.chatForm.addEventListener("submit", (e) => {
      e.preventDefault();
      sendChatMessage(el.messageInput.value, false);
    });

    el.messageInput.addEventListener("input", autoResizeTextarea);
    el.messageInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        sendChatMessage(el.messageInput.value, false);
      }
    });

    // Colar imagem diretamente (Ctrl+V)
    el.messageInput.addEventListener("paste", (e) => {
      const items = e.clipboardData?.items || [];
      for (const item of items) {
        if (item.kind === "file") {
          const f = item.getAsFile();
          if (f) {
            setAttachment(f);
            break;
          }
        }
      }
    });

    // Anexar arquivo & Drag-and-Drop
    el.attachBtn.addEventListener("click", () => el.fileInput.click());
    el.fileInput.addEventListener("change", () => {
      if (el.fileInput.files && el.fileInput.files[0]) {
        setAttachment(el.fileInput.files[0]);
      }
    });
    el.removeAttachmentBtn.addEventListener("click", clearAttachment);

    let dragDepth = 0;
    el.chatPanel.addEventListener("dragenter", (e) => {
      e.preventDefault();
      dragDepth++;
      el.dropOverlay.classList.remove("hidden");
    });
    el.chatPanel.addEventListener("dragover", (e) => e.preventDefault());
    el.chatPanel.addEventListener("dragleave", () => {
      dragDepth--;
      if (dragDepth <= 0) {
        dragDepth = 0;
        el.dropOverlay.classList.add("hidden");
      }
    });
    el.chatPanel.addEventListener("drop", (e) => {
      e.preventDefault();
      dragDepth = 0;
      el.dropOverlay.classList.add("hidden");
      const file = e.dataTransfer?.files?.[0];
      if (file) setAttachment(file);
    });

    // Limpar histórico
    el.clearChatBtn.addEventListener("click", async () => {
      if (!confirm("Deseja limpar o histórico de conversas atual? Suas memórias, tarefas e notas permanecerão intactas.")) {
        return;
      }
      try {
        const res = await apiFetch("/api/history", { method: "DELETE" });
        renderWelcomeState();
        if (res.stats) updateStatsUI(res.stats);
        showToast("Histórico de conversa limpo.");
      } catch (err) {
        showToast(err.message);
      }
    });

    // Drawer
    el.drawerToggleBtn.addEventListener("click", () => openDrawer());
    el.drawerCloseBtn.addEventListener("click", closeDrawer);
    el.drawerBackdrop.addEventListener("click", closeDrawer);
    el.drawerTabs.forEach((btn) =>
      btn.addEventListener("click", () => setDrawerTab(btn.dataset.tab))
    );

    // CRUD Tarefas no Drawer
    el.quickTaskForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const titulo = el.taskTitleInput.value.trim();
      if (!titulo) return;
      try {
        await apiFetch("/api/tasks", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            titulo,
            prazo: el.taskDeadlineInput.value.trim() || null,
            prioridade: el.taskPrioritySelect.value,
          }),
        });
        el.taskTitleInput.value = "";
        el.taskDeadlineInput.value = "";
        await refreshDrawerData();
        showToast("Tarefa adicionada.");
      } catch (err) {
        showToast(err.message);
      }
    });

    el.tasksList.addEventListener("click", async (e) => {
      const toggleBtn = e.target.closest("[data-toggle-task]");
      if (toggleBtn) {
        await apiFetch(`/api/tasks/${toggleBtn.dataset.toggleTask}/toggle`, { method: "PATCH" });
        await refreshDrawerData();
        return;
      }
      const delBtn = e.target.closest("[data-del-task]");
      if (delBtn) {
        await apiFetch(`/api/tasks/${delBtn.dataset.delTask}`, { method: "DELETE" });
        await refreshDrawerData();
        showToast("Tarefa removida.");
      }
    });

    // CRUD Memórias no Drawer
    el.quickMemoryForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const chave = el.memoryKeyInput.value.trim();
      const valor = el.memoryValInput.value.trim();
      if (!chave || !valor) return;
      try {
        await apiFetch("/api/memories", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            chave,
            valor,
            categoria: el.memoryCatInput.value.trim() || "geral",
          }),
        });
        el.memoryKeyInput.value = "";
        el.memoryValInput.value = "";
        await refreshDrawerData();
        showToast("Memória salva.");
      } catch (err) {
        showToast(err.message);
      }
    });

    let memSearchTimer = null;
    el.memorySearchInput.addEventListener("input", () => {
      clearTimeout(memSearchTimer);
      memSearchTimer = setTimeout(refreshDrawerData, 220);
    });

    el.memoriesList.addEventListener("click", async (e) => {
      const delBtn = e.target.closest("[data-del-memory]");
      if (delBtn) {
        await apiFetch(`/api/memories/${delBtn.dataset.delMemory}`, { method: "DELETE" });
        await refreshDrawerData();
        showToast("Memória removida.");
      }
    });

    // CRUD Notas no Drawer
    el.quickNoteForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const titulo = el.noteTitleInput.value.trim();
      const conteudo = el.noteContentInput.value.trim();
      if (!titulo || !conteudo) return;
      try {
        await apiFetch("/api/notes", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            titulo,
            conteudo,
            tag: el.noteTagInput.value.trim() || "geral",
          }),
        });
        el.noteTitleInput.value = "";
        el.noteContentInput.value = "";
        await refreshDrawerData();
        showToast("Nota salva.");
      } catch (err) {
        showToast(err.message);
      }
    });

    el.notesList.addEventListener("click", async (e) => {
      const delBtn = e.target.closest("[data-del-note]");
      if (delBtn) {
        await apiFetch(`/api/notes/${delBtn.dataset.delNote}`, { method: "DELETE" });
        await refreshDrawerData();
        showToast("Nota removida.");
      }
    });

    // PWA Install
    window.addEventListener("beforeinstallprompt", (e) => {
      e.preventDefault();
      state.deferredInstallPrompt = e;
      el.installPwaBtn.classList.remove("hidden");
    });

    el.installPwaBtn.addEventListener("click", async () => {
      if (!state.deferredInstallPrompt) return;
      state.deferredInstallPrompt.prompt();
      const choice = await state.deferredInstallPrompt.userChoice;
      if (choice.outcome === "accepted") {
        el.installPwaBtn.classList.add("hidden");
      }
      state.deferredInstallPrompt = null;
    });
  }

  // ------------------------------------------------------------------------
  // Registro do Service Worker (PWA)
  // ------------------------------------------------------------------------
  function registerServiceWorker() {
    if ("serviceWorker" in navigator) {
      window.addEventListener("load", () => {
        navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(() => {});
      });
    }
  }

  // ------------------------------------------------------------------------
  // Bootstrap
  // ------------------------------------------------------------------------
  async function init() {
    initPinLock();
    bindEvents();
    syncVoiceControlsUI();
    syncModelUI();
    updateGoogleAuthUI();
    handleGoogleAuthCallbackParams();
    startBrtClock();
    startCoreCanvasLoop();
    registerServiceWorker();
    refreshGoogleAuthStatus();

    if ("speechSynthesis" in window) {
      refreshVoices();
      window.speechSynthesis.onvoiceschanged = refreshVoices;
    }

    if (state.pin) {
      const unlocked = await attemptPinUnlock(state.pin, true);
      if (!unlocked) {
        el.lockScreen.classList.remove("hidden");
        el.pinInput.focus();
      }
    } else {
      el.pinInput.focus();
    }
  }

  init();
})();
