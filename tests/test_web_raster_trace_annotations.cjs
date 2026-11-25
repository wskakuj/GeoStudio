// Ink annotations are not parcel boundaries. Exercise actual pixel segmentation.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const context = vm.createContext({});
vm.runInContext(fs.readFileSync(path.join(__dirname,
  '../geostudio/web_app/static/raster_trace.js'), 'utf8'), context);

const width = 360, height = 180;
function paper() {
  const pixels = new Uint8ClampedArray(width * height * 4); pixels.fill(255);
  return pixels;
}
function ink(pixels, x, y, color) {
  for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) {
    const u = Math.round(x) + dx, v = Math.round(y) + dy;
    if (u < 0 || u >= width || v < 0 || v >= height) continue;
    const index = 4 * (v * width + u);
    for (let k = 0; k < 3; k++) pixels[index + k] = Math.min(pixels[index + k], color[k]);
  }
}
function line(pixels, a, b, color) {
  const steps = Math.ceil(Math.hypot(b[0] - a[0], b[1] - a[1]) * 2);
  for (let step = 0; step <= steps; step++)
    ink(pixels, a[0] + (b[0] - a[0]) * step / steps,
      a[1] + (b[1] - a[1]) * step / steps, color);
}
function circle(pixels, x, y, radius, color) {
  for (let angle = 0; angle < Math.PI * 2; angle += .025)
    ink(pixels, x + radius * Math.cos(angle), y + radius * Math.sin(angle), color);
}
function analyze(pixels) {
  return context.traceLandUses(pixels, new Uint8ClampedArray(pixels.length), width, height, 5, 2.5);
}
function geometry(result) {
  return JSON.stringify(Array.from(result.shapes.values(), shape => shape.points));
}

const plain = paper(), black = [20, 20, 20];
for (const [a, b] of [
  [[20, 20], [320, 20]], [[320, 20], [320, 160]],
  [[320, 160], [20, 160]], [[20, 160], [20, 20]], [[160, 20], [160, 160]],
]) line(plain, a, b, black);
const expected = analyze(plain);
assert.equal(expected.shapes.size, 2, 'fixture must contain two enclosed fields');

for (const color of [[25, 40, 195], [20, 155, 65]]) {
  const annotated = plain.slice();
  // A circled figure inside a field, including two closed loops in the digit 8.
  circle(annotated, 70, 65, 24, color);
  circle(annotated, 70, 58, 7, color);
  circle(annotated, 70, 73, 7, color);
  // A long leader crosses multiple fields and reaches a circled figure outside.
  line(annotated, [91, 75], [170, 120], color);
  line(annotated, [170, 120], [335, 90], color);
  circle(annotated, 340, 70, 17, color);
  line(annotated, [340, 60], [340, 78], color);
  // A large closed annotation occupies much of the second field.
  circle(annotated, 237, 94, 47, color);
  const actual = analyze(annotated);
  assert.equal(actual.shapes.size, 2, 'callout circles and digit counters must not become polygons');
  assert.equal(geometry(actual), geometry(expected), 'annotation strokes must not alter field boundaries');
}
console.log('blue and green annotations preserve both field boundaries: OK');
