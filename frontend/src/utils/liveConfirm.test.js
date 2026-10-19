import { test } from 'node:test';
import assert from 'node:assert/strict';
import { tokenRefusal, deadlineFrom, secondsLeft, EXPIRED_NOTE, CHANGED_NOTE } from './liveConfirm.js';

const err = (status, detail) => ({ response: { status, data: { detail } } });

test('maps the server token refusals to short notes', () => {
  assert.equal(tokenRefusal(err(409, 'This confirmation expired or was already used; nothing was sent. Confirm again.')), EXPIRED_NOTE);
  assert.equal(tokenRefusal(err(409, 'Real money needs two taps: confirm once, then send with the token it returns.')), EXPIRED_NOTE);
  assert.equal(tokenRefusal(err(409, 'This confirmation was for a different order; nothing was sent. Confirm again.')), CHANGED_NOTE);
  assert.match(tokenRefusal(err(403, 'This confirmation belongs to another account.')), /another account/);
});

test('other errors are not token refusals', () => {
  assert.equal(tokenRefusal(err(409, 'The market is closed; live orders go only between 9:15 AM and 3:30 PM IST on weekdays.')), null);
  assert.equal(tokenRefusal(err(500, 'confirmation')), null);
  assert.equal(tokenRefusal({}), null);
});

test('countdown', () => {
  assert.equal(deadlineFrom(60, 1000), 61000);
  assert.equal(deadlineFrom(undefined, 0), 60000);
  assert.equal(secondsLeft(61000, 1000), 60);
  assert.equal(secondsLeft(61000, 60500), 1);
  assert.equal(secondsLeft(61000, 70000), 0);
});
