// Colour theme: the system's by default; the button cycles system, light, dark and remembers the choice in this
// browser only. Loaded in <head> so the page never flashes the wrong theme.
(function () {
  var root = document.documentElement;
  var order = ["system", "light", "dark"];
  function read() {
    try { return localStorage.getItem("theme") || "system"; } catch (err) { return "system"; }
  }
  function apply(choice) {
    if (choice === "light" || choice === "dark") root.setAttribute("data-theme", choice);
    else root.removeAttribute("data-theme");
    var btn = document.querySelector("[data-theme-toggle]");
    if (btn) {
      btn.setAttribute("aria-label", "Colour theme: " + choice);
      btn.title = "Colour theme: " + choice;
      btn.textContent = choice === "light" ? "Light" : choice === "dark" ? "Dark" : "Auto";
    }
  }
  apply(read());
  document.addEventListener("DOMContentLoaded", function () {
    apply(read());
    var btn = document.querySelector("[data-theme-toggle]");
    if (!btn) return;
    btn.addEventListener("click", function () {
      var next = order[(order.indexOf(read()) + 1) % order.length];
      try { localStorage.setItem("theme", next); } catch (err) { /* private mode: not remembered */ }
      apply(next);
    });
  });
})();
