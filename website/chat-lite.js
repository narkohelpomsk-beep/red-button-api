/**
 * Упрощённый чат на сайте — запасной режим, если API (полный бот) недоступен.
 * Полный режим: site-chat-gpt.js → /api/chat/* или туннель.
 */
(function () {
  var C = window.RED_BUTTON || {};
  var phone = C.phoneDisplay || "+7 (909) 535-40-90";
  var tg = C.telegramHandle || "@impuls_red_bot";
  var tgUrl = C.telegram || "https://t.me/impuls_red_bot";

  var log = document.getElementById("chat-log");
  var input = document.getElementById("chat-text");
  var sendBtn = document.getElementById("chat-send");
  var quick = document.getElementById("chat-quick");
  if (!log || !input || !sendBtn) return;

  var ctx = {
    whom: null,
    topic: null,
    awaitingStory: false,
  };

  function active() {
    return window.__RB_CHAT_LITE && !window.__RB_FULL_CHAT;
  }

  function norm(t) {
    return (t || "").toLowerCase().replace(/ё/g, "е").trim();
  }

  function isMobileChat() {
    return window.matchMedia("(max-width: 768px)").matches;
  }

  function scrollChatToLatest(preferBot) {
    requestAnimationFrame(function () {
      requestAnimationFrame(function () {
        log.scrollTop = log.scrollHeight;
        if (isMobileChat()) return;
        var bots = log.querySelectorAll(".bubble.bot");
        var el = preferBot && bots.length ? bots[bots.length - 1] : log.lastElementChild;
        if (el && el.scrollIntoView) {
          el.scrollIntoView({ block: "nearest", behavior: "smooth" });
        }
      });
    });
  }

  var typingEl = null;
  var typingTimer = null;

  function showTyping() {
    hideTyping();
    typingEl = document.createElement("div");
    typingEl.className = "bubble bot bubble-typing";
    typingEl.setAttribute("aria-live", "polite");
    typingEl.innerHTML =
      '<span class="typing-label">Денис печатает</span><span class="typing-dots" aria-hidden="true"><span></span><span></span><span></span></span>';
    log.appendChild(typingEl);
    scrollChatToLatest(true);
  }

  function hideTyping() {
    if (typingTimer) {
      clearTimeout(typingTimer);
      typingTimer = null;
    }
    if (typingEl && typingEl.parentNode) {
      typingEl.parentNode.removeChild(typingEl);
    }
    typingEl = null;
  }

  function bubble(text, who) {
    if (!active()) return;
    var d = document.createElement("div");
    d.className = "bubble " + (who === "user" ? "user" : "bot");
    d.textContent = text;
    log.appendChild(d);
    scrollChatToLatest(who === "bot");
  }

  function clearQuick() {
    if (quick) quick.innerHTML = "";
  }

  function showQuick(labels, fn) {
    if (!active() || !quick) return;
    clearQuick();
    labels.forEach(function (label) {
      var b = document.createElement("button");
      b.type = "button";
      b.className = "chat-reply-btn chat-reply-btn--channel";
      b.textContent = label;
      b.addEventListener("click", function () {
        if (!active()) return;
        bubble(label, "user");
        clearQuick();
        showTyping();
        setTimeout(function () {
          hideTyping();
          fn(label);
        }, 380);
      });
      quick.appendChild(b);
    });
    scrollChatToLatest(false);
  }

  function contacts() {
    return (
      "Контакты:\n• Звонок (24/7): " +
      phone +
      "\n• Telegram: " +
      tg +
      " — там полный диалог с кнопками\n• ВК: vk.me/RedButtonHelp\nПри угрозе жизни — 112 или 103."
    );
  }

  function isPhoneNumber(text) {
    var digits = text.replace(/\D/g, "");
    return (
      /^(\+?7|8)?[\s\-()]*\d{3}[\s\-()]*\d{3}[\s\-()]*\d{2}[\s\-()]*\d{2}$/.test(
        text.replace(/\s/g, "")
      ) || /^\d{10,11}$/.test(digits)
    );
  }

  function submitPhoneLead(text) {
    var origin = window.location.origin.replace(/\/$/, "");
    if (!origin || !isPhoneNumber(text)) return;
    var payload = { phone: text, topic: ctx.topic || null };
    fetch(origin + "/api/chat/lead", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }).catch(function () {});
  }

  function matchCrisis(t) {
    return /112|103|срочно|суицид|убью|потерял сознан|не дышит|передоз|реанимац/.test(t);
  }

  function matchSubstance(t) {
    return /снуп|snuf|насвай|nasvay|нюхательн|вейп|vape|спрей|зависим|наркот|алкогол|пью|пьет|пьёт|буха|запой|игроман|колет|колется|шприц|передоз|созависим|наркоман|алкоголик|не могу бросить|срыв|тяга|ломк|амфетамин|марихуан|кокаин|героин|опиат|солей|спайс|гашиш|экстази|употребл|детокс|абстиненц|тремор/.test(
      t
    );
  }

  function matchBullying(t) {
    return /буллинг|травл|издева|однокласс|бьют меня|меня бьют|кибербулл|тролл|дразн|бойкот|сплетн|насмеш|в классе|в школе.*(бьют|трав|издева)/.test(
      t
    );
  }

  function matchFeelings(t) {
    return /мне плохо|плохо мне|тяжело|тревож|грустн|страшн|одинок|не выдерж|не справ|депресс|паник|бессмысл|устал жить|нет сил|плачу|накрывает|больно внутр/.test(
      t
    );
  }

  function matchCallback(t) {
    return /позвон|перезвон|позвонили|оставить номер|номер телефон|созвон/.test(t);
  }

  function replySubstance(t) {
    var intro = "Спасибо, что написали. ";
    if (/снуп|snuf|насвай|nasvay|нюхательн/.test(t)) {
      intro +=
        "Снуп (нюхательный табак) — тоже зависимость, с ней не обязательно справляться в одиночку. ";
    } else if (/вейп|vape|спрей/.test(t)) {
      intro += "Зависимость от вейпа или спрея — реальная проблема, с ней можно работать. ";
    } else {
      intro += "Похоже, речь о зависимости или употреблении — без осуждения, вы не одни. ";
    }
    return (
      intro +
      "На сегодня: не ругать себя; по возможности убрать вещество «под рукой»; один маленький шаг — что хотите изменить первым.\n\n" +
      "Напишите ещё пару слов — что именно беспокоит. Если понадобится живой разговор, подскажу номер или Telegram."
    );
  }

  function replyBullying() {
    return (
      "Травля и буллинг — не ваша вина. Важно не оставаться с этим в одиночку.\n\n" +
      "Что можно сделать:\n" +
      "• рассказать взрослому, которому доверяете (классный руководитель, психолог)\n" +
      "• сохранять скриншоты и факты, если травля в сети\n" +
      "• не отвечать агрессией на агрессию\n\n" +
      "При угрозах жизни или побоях — 112 или 102.\n" +
      "Анонимно: " +
      phone +
      " или " +
      tg
    );
  }

  function replyFeelings() {
    return (
      "«Мне плохо» — уже достаточно, чтобы попросить о помощи. Это не слабость.\n\n" +
      "Сейчас важно не оставаться с этим одному. Напишите ещё одним предложением — что именно давит: тревога, грусть, страх, отношения, зависимость, травля.\n\n" +
      "Я здесь, чтобы выслушать и подсказать шаги. Если захотите живой разговор — скажите «нужен звонок»."
    );
  }

  function replyAwaitingStory(t) {
    if (matchCrisis(t)) return { crisis: true };
    if (matchSubstance(t)) {
      ctx.topic = "substance";
      return {
        reply: replySubstance(t),
        quick: ["Оставить номер для звонка", "Нужны контакты", "Открыть Telegram", "Начать сначала"],
      };
    }
    if (matchBullying(t)) {
      ctx.topic = "bullying";
      return {
        reply: replyBullying(),
        quick: ["Нужны контакты", "Открыть Telegram", "Начать сначала"],
      };
    }
    if (matchFeelings(t)) {
      ctx.topic = "feelings";
      return {
        reply: replyFeelings(),
        quick: ["Зависимость", "Буллинг", "Оставить номер для звонка", "Нужны контакты"],
      };
    }
    if (t.length >= 3) {
      ctx.awaitingStory = false;
      if (matchWantsTalk(t)) {
        return replyHelpRequest();
      }
      return {
        reply:
          "Спасибо, что рассказали. Слышу вас. " +
          "Чтобы подсказать точнее — это ближе к зависимости, травле, тревоге или другому?\n\n" +
          "Или сразу поговорить с человеком: " +
          phone +
          " / " +
          tg,
        quick: ["Зависимость", "Буллинг", "Мне плохо", "Нужны контакты"],
      };
    }
    return {
      reply: "Напишите чуть подробнее — что случилось и что сейчас тяжелее всего?",
      quick: ["Срочно, угроза жизни", "Нужны контакты", "Начать сначала"],
    };
  }

  function matchWantsTalk(t) {
    return /разговар|поговор|поболта|выслуш|ты будешь|будешь со мной|поговоришь|поговорите|помог|нужна помощ|нужен помощ|нужна твоя|нужна ваша|выруч|спаси/.test(
      t
    );
  }

  function replyHelpRequest() {
    return {
      reply:
        "Я здесь, слышу вас. Расскажите своими словами, что случилось — без осуждения. " +
        "Если нужен живой разговор прямо сейчас: " +
        phone +
        " или " +
        tg +
        ".",
      quick: ["Зависимость", "Буллинг", "Мне плохо", "Нужны контакты", "Открыть Telegram"],
    };
  }

  function analyzeFreeText(text) {
    var t = norm(text);
    if (isPhoneNumber(text)) {
      submitPhoneLead(text);
      return {
        reply:
          "Принято. Специалист свяжется с вами. Пока можете продолжить писать здесь или позвонить: " +
          phone +
          ".",
        quick: ["Нужны контакты", "Начать сначала"],
      };
    }
    if (matchCrisis(t)) {
      return {
        reply: "Сейчас главное — безопасность. Звоните 112 или 103.\n\n" + contacts(),
        quick: ["Начать сначала"],
        crisis: true,
      };
    }
    if (t === "зависимость" || /зависим|наркот|алкогол|снуп|вейп/.test(t)) {
      ctx.topic = "substance";
      return {
        reply: replySubstance(t),
        quick: ["Оставить номер для звонка", "Нужны контакты", "Открыть Telegram"],
      };
    }
    if (t === "буллинг" || matchBullying(t)) {
      ctx.topic = "bullying";
      return {
        reply: replyBullying(),
        quick: ["Нужны контакты", "Открыть Telegram", "Начать сначала"],
      };
    }
    if (t === "мне плохо" || matchFeelings(t)) {
      ctx.topic = "feelings";
      return {
        reply: replyFeelings(),
        quick: ["Зависимость", "Буллинг", "Оставить номер для звонка", "Нужны контакты"],
      };
    }
    if (matchCallback(t)) {
      return {
        reply:
          "Напишите номер телефона в поле ниже — передам специалисту. Или позвоните сами: " + phone + ".",
        quick: ["Нужны контакты", "Продолжить в чате"],
      };
    }
    if (matchWantsTalk(t)) {
      return replyHelpRequest();
    }
    if (ctx.awaitingStory) {
      return replyAwaitingStory(t);
    }
    if (matchSubstance(t)) {
      return {
        reply: replySubstance(t),
        quick: ["Оставить номер для звонка", "Нужны контакты", "Открыть Telegram"],
      };
    }
    if (matchBullying(t)) {
      return {
        reply: replyBullying(),
        quick: ["Нужны контакты", "Открыть Telegram"],
      };
    }
    if (matchFeelings(t)) {
      return {
        reply: replyFeelings(),
        quick: ["Зависимость", "Буллинг", "Оставить номер для звонка"],
      };
    }
    return {
      reply:
        "Спасибо, что написали. Чтобы помочь точнее — коротко: зависимость, травля, тревога или другое?\n\n" +
        "Для разговора с человеком: " +
        phone +
        " или " +
        tg +
        " (там полный диалог).",
      quick: ["Зависимость", "Буллинг", "Мне плохо", "Нужны контакты", "Открыть Telegram"],
    };
  }

  function onQuick(label) {
    if (!active()) return;
    var l = norm(label);
    if (label === "Проблема у меня") {
      ctx.whom = "self";
      ctx.awaitingStory = true;
      ctx.topic = null;
      bubble("Расскажите коротко, что случилось и что сейчас сложнее всего?", "bot");
      showQuick(["Срочно, угроза жизни", "Нужны контакты", "Начать сначала"], onQuick);
      return;
    }
    if (label === "Проблема у близкого") {
      ctx.whom = "relative";
      ctx.awaitingStory = true;
      ctx.topic = null;
      bubble(
        "Понятно, волнует близкий человек. Расскажите коротко — что происходит и что вас тревожит?",
        "bot"
      );
      showQuick(["Срочно, угроза жизни", "Нужны контакты", "Начать сначала"], onQuick);
      return;
    }
    if (label === "Зависимость") {
      ctx.topic = "substance";
      ctx.awaitingStory = false;
      bubble(replySubstance("зависимость"), "bot");
      showQuick(["Оставить номер для звонка", "Нужны контакты", "Открыть Telegram"], onQuick);
      return;
    }
    if (label === "Буллинг") {
      ctx.topic = "bullying";
      ctx.awaitingStory = false;
      bubble(replyBullying(), "bot");
      showQuick(["Нужны контакты", "Открыть Telegram", "Начать сначала"], onQuick);
      return;
    }
    if (label === "Мне плохо") {
      ctx.topic = "feelings";
      ctx.awaitingStory = false;
      bubble(replyFeelings(), "bot");
      showQuick(["Зависимость", "Буллинг", "Оставить номер для звонка"], onQuick);
      return;
    }
    if (label === "Оставить номер для звонка" || /позвон|перезвон|позвонили/.test(l)) {
      bubble(
        "Напишите номер телефона в поле ниже — передам специалисту. Или позвоните сами: " + phone + ".",
        "bot"
      );
      showQuick(["Нужны контакты", "Продолжить в чате"], onQuick);
      return;
    }
    if (/контакт|номер/.test(l) && label !== "Оставить номер для звонка") {
      bubble(contacts(), "bot");
      showQuick(["Начать сначала", "Открыть Telegram"], onQuick);
      return;
    }
    if (/сначала|заново/.test(l)) {
      start();
      return;
    }
    if (/продолж/.test(l)) {
      ctx.awaitingStory = true;
      bubble("Пишите свободно — что случилось и что сейчас тревожит.", "bot");
      return;
    }
    if (/срочно|угроз/.test(l)) {
      bubble("Сейчас главное — безопасность. Звоните 112 или 103.\n\n" + contacts(), "bot");
      showQuick(["Начать сначала"], onQuick);
      return;
    }
    if (/telegram|телеграм|открыть telegram/.test(l)) {
      window.open(tgUrl, "_blank", "noopener,noreferrer");
      bubble("Открыл Telegram. Там полный диалог с кнопками — напишите «Начать».", "bot");
      showQuick(["Начать сначала", "Нужны контакты"], onQuick);
      return;
    }
    var result = analyzeFreeText(label);
    bubble(result.reply, "bot");
    showQuick(result.quick, onQuick);
  }

  function sendWithText(t) {
    if (!active()) return;
    var text = (t || input.value || "").trim();
    if (!text) return;
    input.value = "";
    bubble(text, "user");
    clearQuick();
    showTyping();
    var started = Date.now();
    var result = analyzeFreeText(text);
    var wait = Math.max(0, 400 - (Date.now() - started));
    setTimeout(function () {
      hideTyping();
      bubble(result.reply, "bot");
      showQuick(result.quick, onQuick);
    }, wait);
  }

  function start() {
    if (!active()) return;
    ctx.whom = null;
    ctx.topic = null;
    ctx.awaitingStory = false;
    var boot = document.getElementById("chat-boot-msg");
    if (boot) boot.remove();
    log.innerHTML = "";
    bubble("Здравствуйте! Это горячая линия анонимной помощи. Проблема у вас или у близкого?", "bot");
    showQuick(
      ["Проблема у меня", "Проблема у близкого", "Нужны контакты"],
      onQuick
    );
  }

  function activate(fromServerError) {
    window.__RB_FULL_CHAT = false;
    window.__RB_CHAT_LITE = true;
    clearQuick();
    var boot = document.getElementById("chat-boot-msg");
    if (boot) boot.remove();
    log.innerHTML = "";
    if (fromServerError) {
      bubble(
        "Полный чат (как в Telegram) сейчас недоступен — работает упрощённый режим на сайте. " +
          "Можно писать здесь или открыть " +
          tg +
          " для полного диалога.",
        "bot"
      );
    }
    start();
    if (quick && fromServerError) {
      var a = document.createElement("a");
      a.className = "chat-reply-btn chat-reply-btn--channel";
      a.href = tgUrl;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      a.textContent = "Открыть " + tg;
      quick.appendChild(a);
    }
  }

  sendBtn.addEventListener("click", function () {
    if (active()) sendWithText();
  });
  input.addEventListener("keydown", function (e) {
    if (active() && e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendWithText();
    }
  });

  window.RB_LiteChat = {
    activate: activate,
    sendWithText: sendWithText,
    isActive: active,
  };

  if (!window.__RB_DEFER_LITE) {
    window.__RB_CHAT_LITE = true;
    activate(false);
  }
})();
