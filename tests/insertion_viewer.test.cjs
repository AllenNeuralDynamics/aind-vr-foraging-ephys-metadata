const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../code/insertion_viewer.html'), 'utf8');
const context = vm.createContext({});
for (const name of ['parseCSV', 'decodeInsertions', 'rasToScene']) {
  const match = source.match(new RegExp(`^function ${name}\\([^]*?^}`, 'm'));
  assert.ok(match, `Missing function ${name}`);
  vm.runInContext(match[0], context);
}
const plain = value => JSON.parse(JSON.stringify(value));

test('CSV parsing preserves escaped quotes, commas, newlines, BOM and CRLF', () => {
  assert.deepEqual(plain(context.parseCSV('\uFEFFa,b\r\n"hello, ""world""\nline",x\r\n')),
    [['a', 'b'], ['hello, "world"\nline', 'x']]);
  assert.deepEqual(plain(context.parseCSV('a,b\n"",""')), [['a', 'b'], ['', '']]);
});

test('bad CSV and raw tracking input are rejected explicitly', () => {
  for (const value of ['a\n"open', 'a\n"closed"oops', 'a\nbad"quote']) {
    assert.throws(() => context.parseCSV(value), /CSV/);
  }
  assert.throws(() => context.decodeInsertions('Setup No,Mouse\n1,123\n'), /produced by/);
});

test('scene mapping preserves right-handed RAS orientation', () => {
  assert.deepEqual(plain(context.rasToScene([1, 2, 3])), [1, 3, -2]);
  const x = context.rasToScene([1, 0, 0]), y = context.rasToScene([0, 1, 0]);
  const cross = [x[1] * y[2] - x[2] * y[1], x[2] * y[0] - x[0] * y[2], x[0] * y[1] - x[1] * y[0]];
  assert.deepEqual(plain(cross), plain(context.rasToScene([0, 0, 1])));
});

test('target area starts enabled and controls exist', () => {
  assert.match(source, /id="target-visible"[^>]*checked/);
  const ids = new Set(Array.from(source.matchAll(/\bid="([^"]+)"/g), match => match[1]));
  for (const id of ['insertion', 'step', 'target-visible', 'brain-visible', 'all-visible', 'file', 'pose']) {
    assert.ok(ids.has(id), `Missing ${id}`);
  }
});

test('generated real data loads without losing schema JSON or invalid rows', t => {
  const csvPath = path.join(__dirname, '../data/insertion_transforms.csv');
  if (!fs.existsSync(csvPath)) { t.skip('Local generated CSV not present'); return; }
  const rows = context.decodeInsertions(fs.readFileSync(csvPath, 'utf8'));
  assert.ok(rows.length > 0);
  const row = rows.find(row => row.status === 'ok');
  assert.ok(row);
  assert.equal(row.transforms[0].object_type, 'Rotation');
  assert.equal(row.steps.length, 7);
  assert.equal(row.global_coordinate_system.name, 'BREGMA_RAS');
  const rawRows = plain(context.parseCSV(fs.readFileSync(csvPath, 'utf8')));
  rawRows[1][rawRows[0].indexOf('target_id')] = '../362';
  const malformed = rawRows.map(cells => cells.map(value => `"${value.replaceAll('"', '""')}"`).join(',')).join('\n');
  assert.throws(() => context.decodeInsertions(malformed),
    /target identifier/);
});
