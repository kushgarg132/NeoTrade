import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

for (const f of ['Strategies', 'LabRuns', 'LabForward', 'NewsAccuracy']) {
  test(`${f} uses the Settings page shell`, () => {
    const src = readFileSync(new URL(`./${f}.jsx`, import.meta.url), 'utf8');
    assert.ok(src.includes('<SettingsPage') && src.includes('back="/settings/lab"'));
    for (const bad of ['LAB_TABS', 'SectionTabs', 'PaperShell', '<Layout']) assert.ok(!src.includes(bad), bad);
  });
}
