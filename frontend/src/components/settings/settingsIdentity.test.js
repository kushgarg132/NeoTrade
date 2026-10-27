import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const files = [
  './Group.jsx', './Models.jsx', './Panel.jsx', './Notifications.jsx',
  '../../pages/SettingsHome.jsx', '../../pages/Handbook.jsx', '../../pages/OptionChain.jsx',
  '../../pages/LabRuns.jsx', '../../pages/LabForward.jsx',
];
const read = (f) => readFileSync(new URL(f, import.meta.url), 'utf8');

for (const f of files) {
  test(`${f} is on the identity`, () => {
    const s = read(f);
    assert.doesNotMatch(s, /rounded-\[16px\]|-wash\)|shadow-sm|bg-\[var\(--accent\)\] text-\[var\(--surface\)\]/);
  });
}

test('accent fills use accent-ink', () => {
  for (const f of ['../../pages/LabRuns.jsx', '../../pages/LabForward.jsx'])
    assert.match(read(f), /text-\[var\(--accent-ink\)\]/);
});
