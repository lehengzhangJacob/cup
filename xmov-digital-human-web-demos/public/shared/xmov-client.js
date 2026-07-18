(function () {
  const BASE_AVATAR_CONFIG = {
    init_events: [
      {
        type: "SetCharacterCanvasAnchor",
        x_location: 0,
        y_location: 0,
        width: 1,
        height: 1,
      },
    ],
  };

  function normalizeText(text) {
    return String(text || "").replace(/\s+/g, " ").trim();
  }

  function setClassName(el, baseClass, mode) {
    if (!el) {
      return;
    }

    el.className = mode ? `${baseClass} ${baseClass}--${mode}` : baseClass;
  }

  function ensureSharedStyles() {
    if (document.getElementById("xmov-shared-avatar-styles")) {
      return;
    }

    const style = document.createElement("style");
    style.id = "xmov-shared-avatar-styles";
    style.textContent = `
      .xmov-avatar-mount {
        position: relative !important;
        width: 100% !important;
        height: 100% !important;
        overflow: hidden !important;
      }
      .xmov-avatar-mount canvas,
      .xmov-avatar-mount video {
        width: 100% !important;
        height: 100% !important;
        display: block !important;
        object-fit: contain !important;
        object-position: center bottom !important;
      }
      button:disabled:not([id="connectBtn"]) {
        cursor: not-allowed !important;
        filter: grayscale(.25);
        opacity: .52;
      }
    `;
    document.head.appendChild(style);
  }

  window.createXmovClient = function createXmovClient(options) {
    ensureSharedStyles();
    const config = window.__XMOV_CONFIG__ || {};
    const els = {
      mount: document.querySelector(options.mount),
      fallback: document.querySelector(options.fallback),
      caption: document.querySelector(options.caption),
      status: document.querySelector(options.status),
      connect: document.querySelector(options.connect),
      actions: Array.from(document.querySelectorAll(options.actionSelector || "button")).filter(
        (button) => button !== document.querySelector(options.connect),
      ),
    };

    const state = {
      avatar: null,
      connected: false,
      connectingPromise: null,
      speaking: false,
    };

    function log(message, level) {
      const prefix = `[${options.name || "XMOV"}]`;
      if (level === "error") {
        console.error(prefix, message);
      } else {
        console.log(prefix, message);
      }
    }

    function setStatus(text, mode) {
      if (!els.status) {
        return;
      }

      els.status.textContent = text;
      setClassName(els.status, options.statusClass || "status-pill", mode);
    }

    function showCaption(text) {
      if (!els.caption) {
        return;
      }

      const value = normalizeText(text);
      if (!value) {
        els.caption.hidden = true;
        els.caption.textContent = "";
        return;
      }

      els.caption.hidden = false;
      els.caption.textContent = value;
    }

    function setFallbackVisible(visible) {
      if (!els.fallback) {
        return;
      }

      els.fallback.hidden = !visible;
      els.fallback.setAttribute("aria-hidden", visible ? "false" : "true");
      els.fallback.classList.toggle("is-visible", visible);
    }

    function setFallbackSpeaking(speaking) {
      if (!els.fallback) {
        return;
      }

      els.fallback.classList.toggle("is-speaking", speaking);
    }

    function normalizeAvatarDom() {
      if (!els.mount) {
        return;
      }

      els.mount.classList.add("xmov-avatar-mount");
    }

    function setActionsEnabled(enabled) {
      els.actions.forEach((button) => {
        button.disabled = !enabled;
        button.setAttribute("aria-disabled", enabled ? "false" : "true");
      });
    }

    function setConnected(connected) {
      state.connected = connected;
      if (!els.connect) {
        return;
      }

      els.connect.disabled = connected;
      if (connected && options.connectedLabel) {
        els.connect.textContent = options.connectedLabel;
      } else if (!connected && options.connectLabel) {
        els.connect.textContent = options.connectLabel;
      }

      setActionsEnabled(connected);
    }

    async function connect() {
      if (state.avatar) {
        return state.avatar;
      }

      if (state.connectingPromise) {
        return state.connectingPromise;
      }

      if (!config.appId || !config.appSecret || !config.gatewayServer) {
        throw new Error("缺少 XMOV Web 配置");
      }

      setStatus(options.connectingText || "正在准备", "connecting");
      if (els.connect) {
        els.connect.disabled = true;
      }
      setFallbackVisible(true);

      const headers = config.authHeader ? { Authorization: config.authHeader } : undefined;

      state.avatar = new window.XmovAvatar({
        containerId: options.mount,
        appId: config.appId,
        appSecret: config.appSecret,
        gatewayServer: config.gatewayServer,
        headers,
        enableDebugger: false,
        config: Object.assign({}, BASE_AVATAR_CONFIG, options.avatarConfig || {}),
        onWidgetEvent(data) {
          if (data?.type === "subtitle_on") {
            showCaption(data.text || "");
          }

          if (data?.type === "subtitle_off") {
            showCaption("");
          }
        },
        onVoiceStateChange(status) {
          const active = status === "start";
          state.speaking = active;
          setFallbackSpeaking(active);
          if (!active && String(status || "").includes("end")) {
            setFallbackSpeaking(false);
          }
        },
        onMessage(message) {
          if (message?.code && message.code !== 0) {
            log(JSON.stringify(message), "error");
          }
        },
        onStatusChange(status) {
          log(`status: ${status}`);
        },
      });

      await state.avatar.init({
        initModel: "normal",
        onDownloadProgress(progress) {
          log(`progress: ${progress}`);
        },
      });

      state.connected = true;
      normalizeAvatarDom();
      setConnected(true);
      setStatus(options.onlineText || "在线", "online");
      setFallbackVisible(false);
      return state.avatar;
    }

    async function speak(text) {
      const content = normalizeText(text);
      if (!content) {
        return;
      }

      if (!state.avatar) {
        setStatus(options.idleText || "准备就绪", "idle");
        showCaption(options.needConnectText || "请先接入顾问。");
        return;
      }

      showCaption("");
      setFallbackSpeaking(true);
      state.avatar.speak(content, true, true);
    }

    async function connectAndSpeak(text) {
      await connect();
      if (text) {
        await speak(text);
      }
    }

    async function destroy() {
      if (!state.avatar) {
        return;
      }

      try {
        await state.avatar.destroy();
      } catch (error) {
        log(error instanceof Error ? error.message : String(error), "error");
      } finally {
        state.avatar = null;
        state.connected = false;
        setConnected(false);
        setFallbackVisible(true);
        setFallbackSpeaking(false);
        showCaption("");
        setStatus(options.idleText || "准备就绪", "idle");
      }
    }

    setConnected(false);
    setStatus(options.idleText || "准备就绪", "idle");
    if (options.connectLabel && els.connect) {
      els.connect.textContent = options.connectLabel;
    }
    setFallbackVisible(true);
    setActionsEnabled(false);

    window.addEventListener("beforeunload", destroy);

    return {
      state,
      connect,
      speak,
      connectAndSpeak,
      destroy,
      showCaption,
      setStatus,
    };
  };
})();
