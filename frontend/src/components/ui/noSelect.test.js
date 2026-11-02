import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

// Each page picks the control that fits its job (ui/ChipRow, settings/Fields Segmented, a stepper, a sort header).
test('no native dropdown anywhere in the app', () => {
  const src = fileURLToPath(new URL('../..', import.meta.url));
  const files = readdirSync(src, { recursive: true }).filter((f) => f.endsWith('.jsx'));
  assert.ok(files.length > 50, 'the scan must find the source');
  assert.deepEqual(files.filter((f) => readFileSync(src + f, 'utf8').includes('<select')), []);
});
