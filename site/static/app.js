// The feed's filters: search, role, source and status, all in the page (no requests). The filters are kept in the
// address (?q=&role=&source=&status=) so a filtered view can be shared. Without JavaScript every claim is listed.
(function () {
  var form = document.getElementById("filters");
  var list = document.getElementById("claims");
  if (!form || !list) return;
  var items = Array.prototype.slice.call(list.querySelectorAll("li[data-name]"));
  var count = document.getElementById("count");
  var empty = document.getElementById("empty");
  var boxes = Array.prototype.slice.call(form.querySelectorAll("input[name=status]"));
  form.hidden = false;

  var params = new URLSearchParams(location.search);
  if (params.has("q")) form.q.value = params.get("q");
  if (params.has("role")) form.role.value = params.get("role");
  if (params.has("source")) form.source.value = params.get("source");
  if (params.has("status")) {
    var want = params.get("status").split(",");
    boxes.forEach(function (b) { b.checked = want.indexOf(b.value) !== -1; });
  }

  function apply() {
    var words = form.q.value.toLowerCase().split(/\s+/).filter(Boolean);
    var role = form.role.value, source = form.source.value;
    var statuses = boxes.filter(function (b) { return b.checked; }).map(function (b) { return b.value; });
    var shown = 0;
    items.forEach(function (li) {
      var d = li.dataset;
      var ok = (!role || d.role === role) && (!source || d.source === source) &&
        statuses.indexOf(d.status) !== -1 &&
        words.every(function (w) { return d.search.indexOf(w) !== -1; });
      li.hidden = !ok;
      if (ok) shown++;
    });
    count.textContent = shown + " of " + items.length + " claims";
    empty.hidden = shown !== 0;
    var p = new URLSearchParams();
    if (form.q.value) p.set("q", form.q.value);
    if (role) p.set("role", role);
    if (source) p.set("source", source);
    var defaults = boxes.every(function (b) { return b.checked === b.defaultChecked; });
    if (!defaults) p.set("status", statuses.join(","));
    var qs = p.toString();
    history.replaceState(null, "", qs ? "?" + qs : location.pathname);
  }
  form.addEventListener("input", apply);
  form.addEventListener("change", apply);
  form.addEventListener("submit", function (ev) { ev.preventDefault(); });
  apply();
})();
