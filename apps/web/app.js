// Phase 01 web prototype: no live market data or trading actions.
document.querySelectorAll("[data-tool]").forEach((item) => {
  item.addEventListener("click", (event) => {
    event.preventDefault();
    const label = item.querySelector("strong")?.textContent || "This tool";
    window.alert(label + " is planned for a future QUANTNEX phase.");
  });
});
