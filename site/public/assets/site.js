// The site's interactive parts, as Alpine components (Alpine's CSP build, assets/vendor/alpine-csp.min.js, loaded
// after this file). Each is registered by name with Alpine.data and named in the page by x-data, so no expression
// is evaluated from a string and the content security policy needs no 'unsafe-eval'. Every page works without
// JavaScript: the feed and the search page list everything, the map's nodes are plain links, and the theme follows
// the system's.
document.addEventListener("alpine:init", function () {
  var Alpine = window.Alpine;

  function storedTheme() {
    try { return localStorage.getItem("theme") || "system"; } catch (err) { return "system"; }
  }

  // The header's button: cycles system, light and dark, remembered in this browser only (theme.js applies it
  // before the page paints).
  Alpine.data("theme", function () {
    return {
      choice: storedTheme(),
      get label() { return this.choice === "light" ? "Light" : this.choice === "dark" ? "Dark" : "Auto"; },
      get aria() { return "Colour theme: " + this.choice; },
      next: function () {
        var order = ["system", "light", "dark"];
        this.choice = order[(order.indexOf(this.choice) + 1) % order.length];
        try { localStorage.setItem("theme", this.choice); } catch (err) { /* private mode: not remembered */ }
        if (this.choice === "system") document.documentElement.removeAttribute("data-theme");
        else document.documentElement.setAttribute("data-theme", this.choice);
      },
    };
  });

  // The feed's filters: search, role, source and status, all in the page. A claim tried on several configurations
  // carries each of its statuses in data-status and matches if any is checked. Kept in the address
  // (?q=&role=&source=&status=) so a filtered view can be shared.
  Alpine.data("feed", function () {
    return {
      off: true, none: false, countText: "",
      init: function () {
        this.form = this.$root.querySelector("form");
        this.items = Array.prototype.slice.call(this.$root.querySelectorAll("li[data-name]"));
        this.boxes = Array.prototype.slice.call(this.form.querySelectorAll("input[name=status]"));
        var f = this.form, params = new URLSearchParams(location.search);
        if (params.has("q")) f.q.value = params.get("q");
        if (params.has("role")) f.role.value = params.get("role");
        if (params.has("source")) f.source.value = params.get("source");
        if (params.has("status")) {
          var want = params.get("status").split(",");
          this.boxes.forEach(function (b) { b.checked = want.indexOf(b.value) !== -1; });
        }
        this.off = false;
        this.apply();
      },
      apply: function () {
        var f = this.form;
        var words = f.q.value.toLowerCase().split(/\s+/).filter(Boolean);
        var role = f.role.value, source = f.source.value;
        var statuses = this.boxes.filter(function (b) { return b.checked; }).map(function (b) { return b.value; });
        var shown = 0;
        this.items.forEach(function (li) {
          var d = li.dataset;
          var ok = (!role || d.role === role) && (!source || d.source === source) &&
            d.status.split(" ").some(function (st) { return statuses.indexOf(st) !== -1; }) &&
            words.every(function (w) { return d.search.indexOf(w) !== -1; });
          li.hidden = !ok;
          if (ok) shown++;
        });
        this.countText = shown + " of " + this.items.length + " claims";
        this.none = shown === 0;
        var p = new URLSearchParams();
        if (f.q.value) p.set("q", f.q.value);
        if (role) p.set("role", role);
        if (source) p.set("source", source);
        var defaults = this.boxes.every(function (b) { return b.checked === b.defaultChecked; });
        if (!defaults) p.set("status", statuses.join(","));
        var qs = p.toString();
        history.replaceState(null, "", qs ? "?" + qs : location.pathname);
      },
    };
  });

  // Search over data/search.json (fetched from this site only). ?q= from the header's search box fills it in.
  var KIND = { claim: "Claim", paper: "Paper", trial: "Trial", option: "Option", role: "Role", resource: "Resource",
    component: "Component", api: "API", group: "Owner", system: "System", page: "Page" };
  Alpine.data("search", function () {
    return {
      off: true, q: "", rows: [], results: [], countText: "",
      get idle() { return !this.q.trim(); },
      init: function () {
        var self = this;
        this.q = new URLSearchParams(location.search).get("q") || "";
        this.off = false;
        fetch(this.$root.dataset.index, { credentials: "same-origin" }).then(function (r) { return r.json(); })
          .then(function (rows) { self.rows = rows; self.run(); })
          .catch(function () { self.countText = "The search index did not load; everything is listed below."; });
      },
      run: function () {
        var words = this.q.toLowerCase().split(/\s+/).filter(Boolean);
        if (!words.length) { this.results = []; this.countText = ""; this.update(); return; }
        var hits = this.rows.filter(function (r) { return words.every(function (w) { return r.w.indexOf(w) !== -1; }); });
        hits.sort(function (a, b) {
          var at = words.every(function (w) { return a.t.toLowerCase().indexOf(w) !== -1; }) ? 0 : 1;
          var bt = words.every(function (w) { return b.t.toLowerCase().indexOf(w) !== -1; }) ? 0 : 1;
          return at - bt;
        });
        this.results = hits.slice(0, 200).map(function (r) {
          return { u: r.u, t: r.t, d: r.d, s: [r.s, r.st].filter(Boolean).join(" · "), kind: KIND[r.k] || r.k };
        });
        this.countText = hits.length + " found" + (hits.length > 200 ? ", the first 200 shown" : "");
        this.update();
      },
      update: function () {
        var p = new URLSearchParams();
        if (this.q) p.set("q", this.q);
        var qs = p.toString();
        history.replaceState(null, "", qs ? "?" + qs : location.pathname);
      },
    };
  });

  // The map: pointing at (or tabbing to) a node lights it, its links and its neighbours; the checkboxes hide kinds
  // of entity and their links.
  Alpine.data("graph", function () {
    return {
      off: true,
      init: function () {
        this.svg = this.$root.querySelector("svg");
        this.nodes = Array.prototype.slice.call(this.svg.querySelectorAll("[data-id]"));
        this.edges = Array.prototype.slice.call(this.svg.querySelectorAll("path[data-from]"));
        this.off = false;
      },
      hover: function (ev) {
        var node = ev.target.closest ? ev.target.closest("[data-id]") : null;
        if (!node) return;
        this.clear();
        var id = node.getAttribute("data-id"), near = {};
        near[id] = true;
        this.edges.forEach(function (e) {
          var a = e.getAttribute("data-from"), b = e.getAttribute("data-to");
          if (a === id || b === id) { e.classList.add("hl"); near[a] = true; near[b] = true; }
        });
        this.nodes.forEach(function (n) { if (near[n.getAttribute("data-id")]) n.classList.add("hl"); });
        this.svg.classList.add("focus");
      },
      clear: function () {
        this.svg.classList.remove("focus");
        this.svg.querySelectorAll(".hl").forEach(function (x) { x.classList.remove("hl"); });
      },
      filter: function () {
        var on = {};
        this.$root.querySelectorAll("input[name=type]").forEach(function (b) { on[b.value] = b.checked; });
        var shown = {};
        this.nodes.forEach(function (n) {
          var ok = on[n.getAttribute("data-type")] !== false;
          n.classList.toggle("off", !ok);
          shown[n.getAttribute("data-id")] = ok;
        });
        this.edges.forEach(function (e) {
          e.classList.toggle("off", !(shown[e.getAttribute("data-from")] && shown[e.getAttribute("data-to")]));
        });
      },
    };
  });
});
