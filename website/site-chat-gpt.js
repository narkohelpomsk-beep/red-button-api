/**
 * Чат на сайте = Telegram (@impuls_red_bot) через API.
 * Сначала /api/chat/* на том же домене (PHP → Render) — работает в VK/TG и на телефоне.
 * Прямой URL (chat-config.js) — только запасной вариант.
 */
(function () {
  var C = window.RED_BUTTON || {};
  var directApi = (
    C.chatApi ||
    window.RED_BUTTON_CHAT_API ||
    ""
  ).replace(/\/$/, "");

  var phoneDisplay = C.phoneDisplay || "+7 (909) 535-40-90";
  var tgUrl = C.telegram || "https://t.me/impuls_red_bot";
  var tgHandle = C.telegramHandle || "@impuls_red_bot";

  var log = document.getElementById("chat-log");
  var input = document.getElementById("chat-text");
  var sendBtn = document.getElementById("chat-send");
  var quickWrap = document.getElementById("chat-quick");
  if (!log || !input || !sendBtn) return;

  window.__RB_FULL_CHAT = true;
  window.__RB_CHAT_LITE = false;

  var sessionId = "";
  var busy = false;
  var lastFreeText = "";
  var STORAGE_KEY = "rb_web_chat_session";
  var STORAGE_VERSION_KEY = "rb_chat_version";
  var CHAT_BUILD = "27";
  try {
    if (sessionStorage.getItem(STORAGE_VERSION_KEY) !== CHAT_BUILD) {
      sessionStorage.removeItem(STORAGE_KEY);
      sessionStorage.setItem(STORAGE_VERSION_KEY, CHAT_BUILD);
    }
  } catch (e) {}
  var defaultPlaceholder = "Напишите сообщение…";
  var FETCH_TIMEOUT_MS = 55000;
  var busyWatchdogTimer = null;
  function getFetchTimeout() {
    return window.matchMedia("(max-width: 768px)").matches ? 65000 : FETCH_TIMEOUT_MS;
  }
  var KEEP_WARM_MS = 4 * 60 * 1000;
  var typingEl = null;
  var slowHintTimer = null;
  var slowHintTimer2 = null;

  function setTypingLabel(text) {
    if (!typingEl) return;
    var label = typingEl.querySelector(".typing-label");
    if (label) label.textContent = text;
  }

  function showTyping(label) {
    hideTyping();
    typingEl = document.createElement("div");
    typingEl.className = "bubble bot bubble-typing";
    typingEl.setAttribute("aria-live", "polite");
    typingEl.setAttribute("aria-label", label || "Денис печатает");
    typingEl.innerHTML =
      '<span class="typing-label">' +
      (label || "Денис печатает") +
      '</span><span class="typing-dots" aria-hidden="true"><span></span><span></span><span></span></span>';
    log.appendChild(typingEl);
    scrollChatToLatest(true);
    slowHintTimer = setTimeout(function () {
      setTypingLabel("Секунду… готовлю ответ");
    }, 2500);
    slowHintTimer2 = setTimeout(function () {
      setTypingLabel("Сервер просыпается");
    }, 8000);
  }

  function hideTyping() {
    if (slowHintTimer) {
      clearTimeout(slowHintTimer);
      slowHintTimer = null;
    }
    if (slowHintTimer2) {
      clearTimeout(slowHintTimer2);
      slowHintTimer2 = null;
    }
    if (typingEl && typingEl.parentNode) {
      typingEl.parentNode.removeChild(typingEl);
    }
    typingEl = null;
  }

  function pingBackend() {
    if (document.hidden) return;
    var origin = window.location.origin.replace(/\/$/, "");
    var opts = {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    };
    if (origin) {
      fetch(origin + "/api/chat/ping", opts).catch(function () {});
    }
    if (directApi) {
      fetch(directApi + "/api/chat/ping", { method: "GET" }).catch(function () {});
    }
  }

  function isMobileChat() {
    return window.matchMedia("(max-width: 768px)").matches;
  }

  function scrollChatToLatest(preferBot) {
    requestAnimationFrame(function () {
      requestAnimationFrame(function () {
        log.scrollTop = log.scrollHeight;
        if (isMobileChat()) return;
        var lastBot = null;
        if (preferBot) {
          var bots = log.querySelectorAll(".bubble.bot");
          if (bots.length) lastBot = bots[bots.length - 1];
        }
        var el = lastBot || log.lastElementChild;
        if (el && el.scrollIntoView) {
          el.scrollIntoView({ block: "nearest", behavior: "smooth" });
        }
      });
    });
  }

  function afterChatTurn(keepFocus) {
    scrollChatToLatest(true);
    if (isMobileChat()) {
      try {
        input.blur();
      } catch (e) {}
      var chatBox = document.getElementById("chat");
      if (chatBox) {
        chatBox.scrollIntoView({ block: "nearest", behavior: "smooth" });
      }
    } else if (keepFocus) {
      input.focus();
    }
  }

  function clearBoot() {
    var boot = document.getElementById("chat-boot-msg");
    if (boot) boot.remove();
  }

  function addBubble(text, who) {
    if (!text) return;
    var d = document.createElement("div");
    d.className = "bubble " + (who === "user" ? "user" : "bot");
    d.textContent = text;
    log.appendChild(d);
    scrollChatToLatest(who === "bot");
  }

  function clearQuick() {
    if (quickWrap) {
      quickWrap.innerHTML = "";
      quickWrap.className = "chat-quick";
    }
  }

  function showButtons(rows) {
    if (!quickWrap || !rows || !rows.length) {
      clearQuick();
      return;
    }
    clearQuick();
    rows.forEach(function (row) {
      row.forEach(function (label) {
        var btn = document.createElement("button");
        btn.type = "button";
        btn.className = "chat-reply-btn chat-reply-btn--channel";
        btn.textContent = label;
        btn.addEventListener("click", function () {
          if (busy) return;
          input.value = label;
          // busy/watchdog ставит только sendMessage — иначе busy=true
          // и sendMessage сразу выходит: «Ответ задерживается»
          sendMessage();
        });
        quickWrap.appendChild(btn);
      });
    });
    scrollChatToLatest(false);
  }

  function setBusy(on) {
    busy = on;
    sendBtn.disabled = on;
    input.disabled = on;
    if (on) showTyping();
    else {
      clearBusyWatchdog();
      hideTyping();
    }
  }

  function setPhoneMode(on) {
    var wrap = input && input.closest(".chat-input");
    if (wrap) wrap.classList.toggle("chat-input--phone", !!on);
    input.placeholder = on
      ? "Номер телефона, например +79001234567"
      : defaultPlaceholder;
  }

  function showSetupHelp(err) {
    if (window.RB_LiteChat && typeof window.RB_LiteChat.activate === "function") {
      if (sessionId) {
        addBubble(
          "Сейчас не удаётся связаться с сервером. Попробуйте ещё раз через минуту или напишите в Telegram: " +
            tgHandle,
          "bot"
        );
        afterChatTurn(false);
        return;
      }
      window.RB_LiteChat.activate(true);
      return;
    }
    var msg =
      "Чат временно недоступен.\n\n• Telegram: " +
      tgHandle +
      "\n• Звонок: " +
      phoneDisplay;
    addBubble(msg, "bot");
  }

  function looksLikePhone(text) {
    var digits = (text || "").replace(/\D/g, "");
    return digits.length === 10 || digits.length === 11;
  }

  function submitPhoneLead(text) {
    var origin = window.location.origin.replace(/\/$/, "");
    if (!origin || !looksLikePhone(text)) return;
    var payload = { phone: text };
    if (sessionId) payload.session_id = sessionId;
    fetch(origin + "/api/chat/lead", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }).catch(function () {});
  }

  function fetchApi(base, path, body) {
    var ctrl = typeof AbortController !== "undefined" ? new AbortController() : null;
    var timer = null;
    if (ctrl) {
      timer = setTimeout(function () {
        try {
          ctrl.abort();
        } catch (e) {}
      }, getFetchTimeout());
    }
    var opts = {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    };
    if (ctrl) opts.signal = ctrl.signal;

    return fetch(base + path, opts)
      .then(function (r) {
        return r.json().then(function (data) {
          if (!r.ok && data.error !== "session_expired") {
            throw new Error(data.error || "api_error");
          }
          if (!r.ok) return data;
          return data;
        });
      })
      .finally(function () {
        if (timer) clearTimeout(timer);
      });
  }

  function api(path, body) {
    pingBackend();
    var origin = window.location.origin.replace(/\/$/, "");
    var bases = [];
    // Сначала Render HTTPS — там же крутится Telegram-бот и работает GPT
    if (directApi && /^https:\/\//i.test(directApi)) {
      bases.push(directApi);
    }
    // PHP-прокси (тоже должен смотреть на Render)
    if (origin && bases.indexOf(origin) < 0) bases.push(origin);

    function tryNext(i) {
      if (i >= bases.length) {
        return Promise.reject(new Error("backend_unreachable"));
      }
      return fetchApi(bases[i], path, body)
        .then(function (data) {
          var isMsg = path.indexOf("/message") !== -1;
          var reply = data && data.reply ? String(data.reply).trim() : "";
          var hasButtons = !!(data && data.buttons && data.buttons.length);
          if (isMsg && data && !data.error && !reply && !hasButtons) {
            throw new Error("empty_reply");
          }
          // Заглушка без GPT (часто VPS из РФ) — пробуем следующий бэкенд
          if (
            isMsg &&
            data &&
            !data.error &&
            !hasButtons &&
            i + 1 < bases.length &&
            (reply ===
              "Я с вами. Давайте шаг за шагом. Что прямо сейчас сложнее всего?" ||
              reply ===
                "Я на связи. Расскажите коротко, что случилось и что сейчас сложнее всего?")
          ) {
            throw new Error("gpt_stub");
          }
          return data;
        })
        .catch(function () {
          return tryNext(i + 1);
        });
    }
    return tryNext(0);
  }

  function applyResponse(data) {
    clearBusyWatchdog();
    if (data.error && data.error !== "session_expired") {
      showSetupHelp(data.error);
      return Promise.resolve();
    }
    if (data.session_id) {
      sessionId = data.session_id;
      try {
        sessionStorage.setItem(STORAGE_KEY, sessionId);
      } catch (e) {}
    }
    if (data.reply) {
      hideTyping();
      addBubble(data.reply, "bot");
    } else {
      hideTyping();
    }
    showButtons(data.buttons);
    setPhoneMode(!!data.awaiting_phone);
    afterChatTurn(false);
    return Promise.resolve();
  }

  function startChat(opts) {
    opts = opts || {};
    if (!opts.quiet) setBusy(true);
    clearQuick();
    clearBoot();
    var attempt = function (left) {
      return api("/api/chat/start", {})
        .then(function (data) {
          // quiet: только новая session_id, без приветствия в ленте
          if (opts.quiet) {
            if (data && data.session_id) {
              sessionId = data.session_id;
              try {
                sessionStorage.setItem(STORAGE_KEY, sessionId);
              } catch (e) {}
            }
            return data;
          }
          return applyResponse(data);
        })
        .catch(function (e) {
          if (left > 0) {
            return new Promise(function (resolve) {
              setTimeout(resolve, isMobileChat() ? 1200 : 700);
            }).then(function () {
              return attempt(left - 1);
            });
          }
          showSetupHelp(String(e.message || ""));
        });
    };
    return attempt(1)
      .finally(function () {
        if (!opts.quiet) setBusy(false);
      });
  }

  function sendMessage() {
    if (window.RB_LiteChat && window.RB_LiteChat.isActive && window.RB_LiteChat.isActive()) {
      window.RB_LiteChat.sendWithText((input.value || "").trim());
      input.value = "";
      if (!isMobileChat()) input.focus();
      return;
    }
    var text = (input.value || "").trim();
    if (!text || busy) return;
    lastFreeText = text;
    addBubble(text, "user");
    input.value = "";
    clearQuick();
    if (looksLikePhone(text)) {
      submitPhoneLead(text);
    }
    if (!busy) {
      setBusy(true);
      armBusyWatchdog();
    }

    var sendText = function () {
      var payload = { session_id: sessionId };
      if (looksLikePhone(text)) {
        payload.phone = text;
      } else {
        payload.text = text;
      }
      return api("/api/chat/message", payload).then(function (data) {
        var empty =
          data &&
          !data.error &&
          !(data.reply || "").trim() &&
          !(data.buttons && data.buttons.length);
        if (data.error === "session_expired" || empty) {
          sessionId = "";
          try {
            sessionStorage.removeItem(STORAGE_KEY);
          } catch (e) {}
          return startChat({ quiet: true }).then(function () {
            if (!sessionId) return;
            var again = { session_id: sessionId };
            if (looksLikePhone(text)) again.phone = text;
            else again.text = text;
            return api("/api/chat/message", again).then(applyResponse);
          });
        }
        applyResponse(data);
      });
    };

    if (!sessionId) {
      return startChat({ quiet: true })
        .then(function () {
          if (!sessionId) return;
          return sendText();
        })
        .catch(function () {
          showSetupHelp("backend_unreachable");
        })
        .finally(function () {
          setBusy(false);
          afterChatTurn(false);
        });
    }

    sendText()
      .catch(function () {
        showSetupHelp("backend_unreachable");
      })
      .finally(function () {
        setBusy(false);
        afterChatTurn(false);
      });
  }

  sendBtn.addEventListener("click", sendMessage);
  input.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });

  try {
    var saved = sessionStorage.getItem(STORAGE_KEY);
    if (saved) sessionId = saved;
  } catch (e) {}

  function clearBusyWatchdog() {
    if (busyWatchdogTimer) {
      clearTimeout(busyWatchdogTimer);
      busyWatchdogTimer = null;
    }
  }

  function armBusyWatchdog() {
    clearBusyWatchdog();
    var ms = getFetchTimeout() + 8000;
    busyWatchdogTimer = setTimeout(function () {
      busyWatchdogTimer = null;
      if (!busy) return;
      setBusy(false);
      addBubble(
        "Ответ задерживается. Подождите или нажмите кнопку ещё раз.",
        "bot"
      );
      afterChatTurn(false);
    }, ms);
  }

  clearBoot();
  if (sessionId) {
    addBubble("Продолжаем диалог. Напишите или нажмите кнопку.", "bot");
  } else {
    log.innerHTML = "";
    startChat();
  }
  setInterval(pingBackend, KEEP_WARM_MS);
  document.addEventListener("visibilitychange", function () {
    if (!document.hidden) pingBackend();
  });
})();
