/* Filter the local catalogue. Keep the selected source only while it matches. */
(function () {
  "use strict";
  const normalize = value => String(value || "").toLocaleLowerCase("pl")
    .normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/ł/g, "l");
  function matches(group, label, value, url, category, search) {
    const haystack = normalize([group, label, value, url].join(" "));
    return (!category || group === category) &&
      normalize(search).trim().split(/\s+/).every(word => haystack.includes(word));
  }
  if (typeof module === "object" && module.exports) module.exports = {matches};
  if (typeof document === "undefined") return;
  const select = document.getElementById("underlay-preset");
  const category = document.getElementById("underlay-category");
  const search = document.getElementById("underlay-search");
  const count = document.getElementById("underlay-catalog-count");
  if (!select || !category || !search || !count) return;
  const groups = Array.from(select.querySelectorAll("optgroup")).map(group => ({
    label:group.label, options:Array.from(group.children).map(option => option.cloneNode(true))
  }));
  function refresh() {
    const selected = select.value;
    let found = 0, selectedIncluded = false;
    const result = [];
    for (const group of groups) {
      const options = group.options.filter(option => matches(group.label, option.textContent,
        option.value, option.dataset.url, category.value, search.value));
      if (!options.length) continue;
      const node = document.createElement("optgroup");
      node.label = group.label;
      for (const option of options) {
        if (option.value === selected) selectedIncluded = true;
        node.append(option.cloneNode(true));
        found += 1;
      }
      result.push(node);
    }
    // Do not leave an out-of-category source in the dropdown. If it was
    // selected, require an explicit new choice instead of loading a random WMS.
    if (!selectedIncluded) {
      const placeholder = document.createElement("option");
      placeholder.value = "";
      placeholder.textContent = found ? "Wybierz usługę…" : "Brak pasujących usług";
      placeholder.disabled = true;
      result.unshift(placeholder);
    }
    select.replaceChildren(...result);
    select.value = selectedIncluded ? selected : "";
    select.disabled = found === 0;
    count.textContent = "Wyniki: " + found + " z " +
      groups.reduce((sum, group) => sum + group.options.length, 0) +
      (!found ? " · zmień filtr lub wpisz inną nazwę" : "");
    // Notify the existing source-change handler so it clears stale layer
    // choices and cancels an outstanding capabilities request, if any.
    if (selected !== select.value) {
      select.dispatchEvent(new Event("change", {bubbles:true}));
    }
  }
  category.addEventListener("change", refresh);
  search.addEventListener("input", refresh);
})();
