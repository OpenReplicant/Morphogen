// Colour theme, applied before the page paints so it never flashes the wrong one: the system's by default, or the
// choice made with the header's button (site.js), remembered in this browser only.
(function () {
  try {
    var t = localStorage.getItem("theme");
    if (t === "light" || t === "dark") document.documentElement.setAttribute("data-theme", t);
  } catch (err) { /* storage blocked: follow the system */ }
})();
