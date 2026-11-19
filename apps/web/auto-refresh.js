(() => {
  "use strict";

  // Existing live streams and page-specific timers already own these controls.
  // All remaining refresh-only actions are scheduled here so the workspace
  // never depends on a user clicking a refresh button.
  const schedules = {
    p7RefreshPaper: 30000,
    p11Refresh: 60000,
    paperEngineRefresh: 60000,
    paperUniverseRefresh: 300000,
    p8ResearchRefresh: 120000,
    p9Refresh: 30000,
    refreshSystemBackups: 300000,
    refreshSystemAudit: 60000,
    watchlistRefresh: 30000,
    forexDeskRefresh: 30000,
    cryptoDeskRefresh: 30000,
    goldDeskRefresh: 30000,
    historyRefresh: 60000,
    goalsRefresh: 60000,
    strategyLibraryRefresh: 60000,
    portfolioMonitorRefresh: 30000,
    bnRefresh: 30000,
    integrationRefresh: 60000
  };

  const existingAutomaticControls = [
    "p7RefreshMarkets", "qxSignalLedgerRefresh", "calendarRefresh",
    "paperEngineMonitor", "paperEngineEventsRefresh", "pcRefresh"
  ];

  function hideRefreshControls() {
    [...Object.keys(schedules), ...existingAutomaticControls].forEach(id => {
      const button = document.getElementById(id);
      if (!button) return;
      button.hidden = true;
      button.setAttribute("aria-hidden", "true");
      button.tabIndex = -1;
      button.dataset.automaticRefresh = "true";
    });
  }

  function runRefresh(id, interval) {
    if (document.visibilityState !== "visible") return;
    const button = document.getElementById(id);
    if (!button || button.disabled || button.dataset.autoRefreshBusy === "true") return;
    button.dataset.autoRefreshBusy = "true";
    try {
      button.click();
    } finally {
      // Refresh handlers may start async work; let their own disabled/busy
      // guards prevent overlap and clear this lightweight dispatch lock soon.
      window.setTimeout(() => { delete button.dataset.autoRefreshBusy; }, Math.max(10000, Math.min(60000, interval - 1000)));
    }
  }

  function start() {
    hideRefreshControls();
    Object.entries(schedules).forEach(([id, interval]) => {
      window.setInterval(() => runRefresh(id, interval), interval);
    });
    // Re-hide controls if a page re-renders its toolbar.
    const observer = new MutationObserver(hideRefreshControls);
    observer.observe(document.body, { childList: true, subtree: true });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start, { once: true });
  } else {
    start();
  }
})();
