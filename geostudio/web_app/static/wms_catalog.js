/* Local catalogue filtering: never sends a request or changes the chosen source. */
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
    const current = groups.flatMap(group => group.options).find(option => option.value === selected);
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
    if (current && !selectedIncluded) {
      const pinned = document.createElement("optgroup");
      pinned.label = "Bieżące źródło (poza filtrem)";
      pinned.append(current.cloneNode(true));
      result.unshift(pinned);
    }
    select.replaceChildren(...result);
    if (current) select.value = selected;
    count.textContent = "Wyniki: " + found + " z " +
      groups.reduce((sum, group) => sum + group.options.length, 0) +
      (!found ? " · zmień filtr lub wpisz inną nazwę" : "") +
      (current && !selectedIncluded ? " · zachowano bieżące źródło" : "");
  }
  category.addEventListener("change", refresh);
  search.addEventListener("input", refresh);
})();
