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
      '<span class="typing-label">Denis is typing</span><span class="typing-dots" aria-hidden="true"><span></span><span></span><span></span></span>';
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
      "Contacts:\n• Call (24/7): " +
      phone +
      "\n• Telegram: " +
      tg +
      " — full guided chat with buttons\n• VK: vk.me/RedButtonHelp\nIf life is at risk — call 112 or 103."
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
    var intro = "Thank you for writing. ";
    if (/снуп|snuf|насвай|nasvay|нюхательн/.test(t)) {
      intro +=
        "Snus (smokeless tobacco) is also an addiction — you don't have to face it alone. ";
    } else if (/вейп|vape|спрей/.test(t)) {
      intro += "Vape or spray addiction is a real issue, and it can be worked on. ";
    } else {
      intro += "It sounds like addiction or substance use — no judgment, you are not alone. ";
    }
    return (
      intro +
      "For today: don't blame yourself; if you can, remove easy access to the substance; one small step — what do you want to change first?\n\n" +
      "Write a couple more words about what worries you most. If you need a live conversation, I can share a phone number or Telegram."
    );
  }

  function replyBullying() {
    return (
      "Bullying is not your fault. It matters not to face this alone.\n\n" +
      "What you can do:\n" +
      "• tell a trusted adult (teacher, counselor)\n" +
      "• keep screenshots and facts if the bullying is online\n" +
      "• do not respond to aggression with aggression\n\n" +
      "If there are threats to life or assault — call 112 or 102.\n" +
      "Anonymously: " +
      phone +
      " or " +
      tg
    );
  }

  function replyFeelings() {
    return (
      "Saying “I feel bad” is already enough to ask for help. That is not weakness.\n\n" +
      "Right now it matters not to stay alone with this. In one more sentence, what is weighing on you: anxiety, sadness, fear, relationships, addiction, bullying.\n\n" +
      "I'm here to listen and suggest next steps. If you want a live conversation — say “need a call”."
    );
  }

  function replyAwaitingStory(t) {
    if (matchCrisis(t)) return { crisis: true };
    if (matchSubstance(t)) {
      ctx.topic = "substance";
      return {
        reply: replySubstance(t),
        quick: ["Leave a callback number", "Need contacts", "Open Telegram", "Start over"],
      };
    }
    if (matchBullying(t)) {
      ctx.topic = "bullying";
      return {
        reply: replyBullying(),
        quick: ["Need contacts", "Open Telegram", "Start over"],
      };
    }
    if (matchFeelings(t)) {
      ctx.topic = "feelings";
      return {
        reply: replyFeelings(),
        quick: ["Addiction", "Bullying", "Leave a callback number", "Need contacts"],
      };
    }
    if (t.length >= 3) {
      ctx.awaitingStory = false;
      if (matchWantsTalk(t)) {
        return replyHelpRequest();
      }
      return {
        reply:
          "Thank you for sharing. I hear you. " +
          "To help more precisely — is this closer to addiction, bullying, anxiety, or something else?\n\n" +
          "Or talk to a person right away: " +
          phone +
          " / " +
          tg,
        quick: ["Addiction", "Bullying", "I feel bad", "Need contacts"],
      };
    }
    return {
      reply: "Please share a bit more — what happened and what feels hardest right now?",
      quick: ["Urgent, life at risk", "Need contacts", "Start over"],
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
        "I'm here, I hear you. Tell me in your own words what happened — no judgment. " +
        "If you need a live conversation right now: " +
        phone +
        " or " +
        tg +
        ".",
      quick: ["Addiction", "Bullying", "I feel bad", "Need contacts", "Open Telegram"],
    };
  }

  function analyzeFreeText(text) {
    var t = norm(text);
    if (isPhoneNumber(text)) {
      submitPhoneLead(text);
      return {
        reply:
          "Got it. A specialist will contact you. Meanwhile you can keep writing here or call: " +
          phone +
          ".",
        quick: ["Need contacts", "Start over"],
      };
    }
    if (matchCrisis(t)) {
      return {
        reply: "Safety comes first right now. Call 112 or 103.\n\n" + contacts(),
        quick: ["Start over"],
        crisis: true,
      };
    }
    if (t === "зависимость" || t === "addiction" || /зависим|наркот|алкогол|снуп|вейп|addiction|drug|alcohol|vape/.test(t)) {
      ctx.topic = "substance";
      return {
        reply: replySubstance(t),
        quick: ["Leave a callback number", "Need contacts", "Open Telegram"],
      };
    }
    if (t === "буллинг" || t === "bullying" || matchBullying(t)) {
      ctx.topic = "bullying";
      return {
        reply: replyBullying(),
        quick: ["Need contacts", "Open Telegram", "Start over"],
      };
    }
    if (t === "мне плохо" || t === "i feel bad" || matchFeelings(t)) {
      ctx.topic = "feelings";
      return {
        reply: replyFeelings(),
        quick: ["Addiction", "Bullying", "Leave a callback number", "Need contacts"],
      };
    }
    if (matchCallback(t)) {
      return {
        reply:
          "Enter your phone number below — I will pass it to a specialist. Or call yourself: " + phone + ".",
        quick: ["Need contacts", "Continue in chat"],
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
        quick: ["Leave a callback number", "Need contacts", "Open Telegram"],
      };
    }
    if (matchBullying(t)) {
      return {
        reply: replyBullying(),
        quick: ["Need contacts", "Open Telegram"],
      };
    }
    if (matchFeelings(t)) {
      return {
        reply: replyFeelings(),
        quick: ["Addiction", "Bullying", "Leave a callback number"],
      };
    }
    return {
      reply:
        "Thank you for writing. To help more precisely — briefly: addiction, bullying, anxiety, or something else?\n\n" +
        "To talk to a person: " +
        phone +
        " or " +
        tg +
        " (full guided chat).",
      quick: ["Addiction", "Bullying", "I feel bad", "Need contacts", "Open Telegram"],
    };
  }

  function onQuick(label) {
    if (!active()) return;
    var l = norm(label);
    if (label === "The problem is mine" || label === "Проблема у меня") {
      ctx.whom = "self";
      ctx.awaitingStory = true;
      ctx.topic = null;
      bubble("Briefly tell me what happened and what feels hardest right now?", "bot");
      showQuick(["Urgent, life at risk", "Need contacts", "Start over"], onQuick);
      return;
    }
    if (label === "A loved one has a problem" || label === "Проблема у близкого") {
      ctx.whom = "relative";
      ctx.awaitingStory = true;
      ctx.topic = null;
      bubble(
        "I understand — you’re worried about someone close. Briefly tell me what’s going on and what concerns you most?",
        "bot"
      );
      showQuick(["Urgent, life at risk", "Need contacts", "Start over"], onQuick);
      return;
    }
    if (label === "Addiction" || label === "Зависимость") {
      ctx.topic = "substance";
      ctx.awaitingStory = false;
      bubble(replySubstance("addiction"), "bot");
      showQuick(["Leave a callback number", "Need contacts", "Open Telegram"], onQuick);
      return;
    }
    if (label === "Bullying" || label === "Буллинг") {
      ctx.topic = "bullying";
      ctx.awaitingStory = false;
      bubble(replyBullying(), "bot");
      showQuick(["Need contacts", "Open Telegram", "Start over"], onQuick);
      return;
    }
    if (label === "I feel bad" || label === "Мне плохо") {
      ctx.topic = "feelings";
      ctx.awaitingStory = false;
      bubble(replyFeelings(), "bot");
      showQuick(["Addiction", "Bullying", "Leave a callback number"], onQuick);
      return;
    }
    if (
      label === "Leave a callback number" ||
      label === "Оставить номер для звонка" ||
      /позвон|перезвон|позвонили|callback|leave a callback/.test(l)
    ) {
      bubble(
        "Enter your phone number below — I will pass it to a specialist. Or call yourself: " + phone + ".",
        "bot"
      );
      showQuick(["Need contacts", "Continue in chat"], onQuick);
      return;
    }
    if (
      (/контакт|номер|need contacts|contacts/.test(l) || label === "Need contacts") &&
      label !== "Leave a callback number" &&
      label !== "Оставить номер для звонка"
    ) {
      bubble(contacts(), "bot");
      showQuick(["Start over", "Open Telegram"], onQuick);
      return;
    }
    if (/сначала|заново|start over/.test(l)) {
      start();
      return;
    }
    if (/продолж|continue in chat/.test(l)) {
      ctx.awaitingStory = true;
      bubble("Write freely — what happened and what worries you most right now.", "bot");
      return;
    }
    if (/срочно|угроз|urgent|life at risk/.test(l)) {
      bubble("Safety comes first right now. Call 112 or 103.\n\n" + contacts(), "bot");
      showQuick(["Start over"], onQuick);
      return;
    }
    if (/telegram|телеграм|открыть telegram|open telegram/.test(l)) {
      window.open(tgUrl, "_blank", "noopener,noreferrer");
      bubble("Opened Telegram. There you’ll find the full guided chat with buttons — send “Start”.", "bot");
      showQuick(["Start over", "Need contacts"], onQuick);
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
    bubble("Hello! This is an anonymous help hotline. Is the problem yours or a loved one’s?", "bot");
    showQuick(
      ["The problem is mine", "A loved one has a problem", "Need contacts"],
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
        "The full chat (like in Telegram) is unavailable right now — a simplified mode is running on the site. " +
          "You can write here or open " +
          tg +
          " for the full conversation.",
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
      a.textContent = "Open " + tg;
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
