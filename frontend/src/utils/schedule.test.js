import test from 'node:test';
import assert from 'node:assert/strict';
import { clock12, clockTimes } from './schedule.js';

test('clock12 formats 24-hour times', () => {
  assert.equal(clock12('16:00'), '4:00 PM');
  assert.equal(clock12('09:15'), '9:15 AM');
  assert.equal(clock12('12:05'), '12:05 PM');
  assert.equal(clock12('00:30'), '12:30 AM');
});

test('clockTimes skips non-time fields', () => {
  assert.deepEqual(clockTimes({ plan: '08:45', exit_check_minutes: 15 }), { plan: '8:45 AM' });
});
