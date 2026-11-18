(function (root) {
  "use strict";

  const COLOMBO = "Asia/Colombo";
  const NEW_YORK = "America/New_York";
  const WEEKDAYS = new Set([1, 2, 3, 4, 5]);
  const WEEKDAY_INDEX = { Sun: 0, Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6 };
  const SESSIONS = [
    { id: "sydney", name: "Sydney", flag: "🇦🇺", zone: "Australia/Sydney", open: "08:00", close: "17:00" },
    { id: "asia", name: "Asia · Tokyo", flag: "🌏", zone: "Asia/Tokyo", open: "09:00", close: "18:00" },
    { id: "london", name: "London", flag: "🇬🇧", zone: "Europe/London", open: "08:00", close: "17:00" },
    { id: "new-york", name: "New York", flag: "🇺🇸", zone: NEW_YORK, open: "08:00", close: "17:00" }
  ];

  const formatterCache = new Map();
  function formatter(zone, options) {
    const key = zone + "|" + JSON.stringify(options);
    if (!formatterCache.has(key)) formatterCache.set(key, new Intl.DateTimeFormat("en-GB", Object.assign({ timeZone: zone }, options)));
    return formatterCache.get(key);
  }

  function zonedParts(date, zone) {
    const parts = formatter(zone, {
      year: "numeric", month: "2-digit", day: "2-digit",
      weekday: "short", hour: "2-digit", minute: "2-digit",
      second: "2-digit", hourCycle: "h23"
    }).formatToParts(date);
    const values = {};
    parts.forEach(function (part) { if (part.type !== "literal") values[part.type] = part.value; });
    return {
      year: Number(values.year), month: Number(values.month), day: Number(values.day),
      weekday: WEEKDAY_INDEX[values.weekday], hour: Number(values.hour),
      minute: Number(values.minute), second: Number(values.second)
    };
  }

  function parseClock(value) {
    const parts = value.split(":").map(Number);
    return parts[0] * 60 + parts[1];
  }

  function wallTimeToUtc(dateParts, minuteOfDay, zone) {
    const hour = Math.floor(minuteOfDay / 60);
    const minute = minuteOfDay % 60;
    const desired = Date.UTC(dateParts.year, dateParts.month - 1, dateParts.day, hour, minute, 0);
    let guess = desired;
    for (let attempt = 0; attempt < 5; attempt += 1) {
      const observedParts = zonedParts(new Date(guess), zone);
      const observed = Date.UTC(
        observedParts.year, observedParts.month - 1, observedParts.day,
        observedParts.hour, observedParts.minute, observedParts.second
      );
      const correction = desired - observed;
      guess += correction;
      if (correction === 0) break;
    }
    return new Date(guess);
  }

  function isOpenAt(now, session) {
    const local = zonedParts(now, session.zone);
    const minute = local.hour * 60 + local.minute;
    return WEEKDAYS.has(local.weekday) && minute >= parseClock(session.open) && minute < parseClock(session.close);
  }

  function nextTransition(now, session) {
    if (isOpenAt(now, session)) {
      const local = zonedParts(now, session.zone);
      return {
        type: "close",
        at: wallTimeToUtc(local, parseClock(session.close), session.zone)
      };
    }

    const localNow = zonedParts(now, session.zone);
    for (let offset = 0; offset <= 8; offset += 1) {
      const date = new Date(Date.UTC(localNow.year, localNow.month - 1, localNow.day + offset));
      const target = {
        year: date.getUTCFullYear(),
        month: date.getUTCMonth() + 1,
        day: date.getUTCDate()
      };
      if (!WEEKDAYS.has(date.getUTCDay())) continue;
      const opensAt = wallTimeToUtc(target, parseClock(session.open), session.zone);
      if (opensAt.getTime() > now.getTime()) return { type: "open", at: opensAt };
    }
    return { type: "open", at: new Date(now.getTime() + 8 * 86400000) };
  }

  function formatTime(date, zone) {
    return formatter(zone, { hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23" }).format(date);
  }

  function formatDate(date, zone) {
    return formatter(zone, { weekday: "short", day: "2-digit", month: "short", year: "numeric" }).format(date);
  }

  function formatOffset(date, zone) {
    return formatter(zone, { timeZoneName: "shortOffset" }).formatToParts(date)
      .filter(function (part) { return part.type === "timeZoneName"; })
      .map(function (part) { return part.value; })[0] || zone;
  }

  function formatDuration(milliseconds) {
    const seconds = Math.max(0, Math.ceil(milliseconds / 1000));
    const days = Math.floor(seconds / 86400);
    const hours = Math.floor((seconds % 86400) / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const remainder = seconds % 60;
    if (days) return days + "d " + String(hours).padStart(2, "0") + "h";
    if (hours) return hours + "h " + String(minutes).padStart(2, "0") + "m";
    return minutes + "m " + String(remainder).padStart(2, "0") + "s";
  }

  function sessionSnapshot(now, session) {
    const open = isOpenAt(now, session);
    const transition = nextTransition(now, session);
    const local = zonedParts(now, session.zone);
    const todayOpen = wallTimeToUtc(local, parseClock(session.open), session.zone);
    const todayClose = wallTimeToUtc(local, parseClock(session.close), session.zone);
    return {
      id: session.id,
      name: session.name,
      flag: session.flag,
      zone: session.zone,
      open: open,
      status: open ? "OPEN" : "CLOSED",
      transitionType: transition.type,
      transitionAt: transition.at,
      countdown: formatDuration(transition.at.getTime() - now.getTime()),
      localHours: session.open + "–" + session.close,
      colomboHours: formatTime(todayOpen, COLOMBO).slice(0, 5) + "–" + formatTime(todayClose, COLOMBO).slice(0, 5)
    };
  }

  function getSnapshot(now) {
    const instant = now instanceof Date ? now : new Date(now || Date.now());
    const sessions = SESSIONS.map(function (session) { return sessionSnapshot(instant, session); });
    const active = sessions.filter(function (session) { return session.open; });
    const transitions = sessions.slice().sort(function (a, b) {
      return a.transitionAt.getTime() - b.transitionAt.getTime();
    });
    const next = transitions[0] || null;
    return {
      now: instant,
      colombo: {
        time: formatTime(instant, COLOMBO),
        date: formatDate(instant, COLOMBO),
        offset: formatOffset(instant, COLOMBO)
      },
      newYork: {
        time: formatTime(instant, NEW_YORK),
        date: formatDate(instant, NEW_YORK),
        offset: formatOffset(instant, NEW_YORK)
      },
      sessions: sessions,
      active: active,
      overlap: active.length > 1,
      next: next
    };
  }

  function createText(tag, className, value) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (value !== undefined) node.textContent = value;
    return node;
  }

  function renderClock(prefix, clock) {
    const time = document.getElementById(prefix + "Time");
    const date = document.getElementById(prefix + "Date");
    const offset = document.getElementById(prefix + "Offset");
    if (time) time.textContent = clock.time;
    if (date) date.textContent = clock.date;
    if (offset) offset.textContent = clock.offset;
  }

  function renderSessions(snapshot) {
    const active = document.getElementById("qxSessionActive");
    const list = document.getElementById("qxSessionList");
    const next = document.getElementById("qxSessionNext");
    const overlap = document.getElementById("qxSessionOverlap");

    if (active) {
      active.dataset.state = snapshot.active.length ? "open" : "closed";
      const title = snapshot.active.length
        ? (snapshot.overlap ? snapshot.active.map(function (item) { return item.name.replace(" · Tokyo", ""); }).join(" + ") + " OVERLAP" : snapshot.active[0].name + " SESSION")
        : "NO MAJOR SESSION OPEN";
      active.textContent = title;
    }

    if (overlap) {
      overlap.hidden = !snapshot.overlap;
      overlap.textContent = snapshot.overlap
        ? "Session overlap · " + snapshot.active.map(function (item) { return item.name.replace(" · Tokyo", ""); }).join(" + ")
        : "";
    }

    if (list) {
      list.replaceChildren();
      snapshot.sessions.forEach(function (session) {
        const row = createText("div", "qx-session-row");
        row.dataset.state = session.open ? "open" : "closed";
        const identity = createText("div", "qx-session-identity");
        identity.append(createText("span", "qx-session-flag", session.flag));
        const labels = createText("div", "qx-session-labels");
        labels.append(createText("strong", "", session.name));
        labels.append(createText("small", "", session.localHours + " local · SL " + session.colomboHours));
        identity.append(labels);
        const state = createText("div", "qx-session-state");
        state.append(createText("strong", "", session.open ? "LIVE" : "CLOSED"));
        state.append(createText("small", "", (session.open ? "Closes in " : "Opens in ") + session.countdown));
        row.append(identity, state);
        list.append(row);
      });
    }

    if (next) {
      if (snapshot.next) {
        const verb = snapshot.next.transitionType === "close" ? "closes" : "opens";
        next.textContent = "NEXT · " + snapshot.next.flag + " " + snapshot.next.name + " " + verb + " in " + snapshot.next.countdown;
      } else {
        next.textContent = "Session schedule unavailable";
      }
    }
  }

  function update() {
    const snapshot = getSnapshot(new Date());
    renderClock("qxColombo", snapshot.colombo);
    renderClock("qxNewYork", snapshot.newYork);
    renderSessions(snapshot);
  }

  function init() {
    if (!document.getElementById("qxMarketSessions")) return;
    update();
    const timer = root.setInterval(update, 1000);
    document.addEventListener("visibilitychange", function () {
      if (!document.hidden) update();
    });
    root.addEventListener("beforeunload", function () { root.clearInterval(timer); });
  }

  const api = {
    sessions: SESSIONS,
    getSnapshot: getSnapshot,
    isOpenAt: isOpenAt,
    nextTransition: nextTransition,
    wallTimeToUtc: wallTimeToUtc,
    formatDuration: formatDuration
  };
  root.QuantnexMarketSessions = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (typeof document !== "undefined") init();
})(typeof window !== "undefined" ? window : globalThis);
