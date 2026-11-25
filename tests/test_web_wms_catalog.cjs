/* Exercise the served catalogue script against options parsed from the real HTML.
 * This small DOM harness checks event-driven behavior without a network or browser.
 */
const fs = require("node:fs");
const vm = require("node:vm");
const assert = require("node:assert/strict");
const {groups, script} = JSON.parse(fs.readFileSync(0, "utf8"));

class Element {
  constructor(tag) {
    this.tag = tag;
    this.children = [];
    this.dataset = {};
    this.value = "";
    this.textContent = "";
    this.disabled = false;
    this.listeners = {};
  }
  cloneNode(deep) {
    const node = new Element(this.tag);
    Object.assign(node, {label:this.label, value:this.value,
      textContent:this.textContent, disabled:this.disabled, dataset:{...this.dataset}});
    if (deep) node.children = this.children.map(child => child.cloneNode(true));
    return node;
  }
  append(...nodes) {this.children.push(...nodes);}
  replaceChildren(...nodes) {
    this.children = nodes;
    if (this.tag === "select") this.value = this.options.find(option => !option.disabled)?.value || "";
  }
  get options() {
    return this.children.flatMap(child => child.tag === "optgroup" ? child.children : [child]);
  }
  querySelectorAll(tag) {return this.children.filter(child => child.tag === tag);}
  addEventListener(name, listener) {(this.listeners[name] ||= []).push(listener);}
  dispatchEvent(event) {for (const listener of this.listeners[event.type] || []) listener(event);}
}
const fields = Object.fromEntries(["underlay-preset", "underlay-category",
  "underlay-search", "underlay-catalog-count"].map(id => [id,new Element("select")]));
const select = fields["underlay-preset"], category = fields["underlay-category"];
const search = fields["underlay-search"], count = fields["underlay-catalog-count"];
for (const group of groups) {
  const node = new Element("optgroup");
  node.label = group.label;
  for (const item of group.options) {
    const option = new Element("option");
    option.value = item.value;
    option.textContent = item.text.trim();
    option.dataset.url = item.url;
    node.append(option);
  }
  select.append(node);
}
select.value = "standard";
let changes = [];
select.addEventListener("change", () => changes.push(select.value));
const document = {getElementById:id => fields[id], createElement:tag => new Element(tag)};
vm.runInNewContext(script, {document, Event});
const values = () => select.options.filter(option => option.value !== "").map(option => option.value);
const setCategory = value => {category.value = value; category.dispatchEvent(new Event("change"));};
const setSearch = value => {search.value = value; search.dispatchEvent(new Event("input"));};

assert.equal(values().length,95);
const forests = groups.find(group => group.options.some(item => item.value === "bdl_basic"));
setCategory(forests.label);
assert.equal(values().length,13);
assert.ok(values().every(value => value.startsWith("bdl_")));
assert.equal(select.value,"");
assert.deepEqual(changes,[""]);
assert.match(count.textContent,/13 z 95/);
select.value = "bdl_hunting";
setSearch("obwody lowieckie");
assert.deepEqual(values(),["bdl_hunting"]);
assert.equal(select.value,"bdl_hunting");
assert.equal(changes.length,1,"a still-matching choice must not fire change");
setSearch("brak-takiej-uslugi-12345");
assert.deepEqual(values(),[]);
assert.equal(select.disabled,true);
assert.equal(select.value,"");
assert.deepEqual(changes,["",""]);
setSearch("");
assert.equal(select.disabled,false);
assert.equal(values().length,13);
assert.equal(select.value,"");

for (const group of groups) {
  setCategory(group.label);
  assert.deepEqual(values(),group.options.map(option => option.value));
  assert.equal(select.value,"");
}
setCategory("");
assert.equal(values().length,95);
setSearch("KIUT");
assert.deepEqual(values(),["gugik_kiut"]);
setSearch("");
assert.equal(values().length,95);
