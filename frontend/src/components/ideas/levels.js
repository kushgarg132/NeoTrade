/** Price levels keep their paise (inr rounds to rupees). */
export const px = (n) => (n == null ? '—' : `₹${n.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`);

/** Reward : risk from the idea's own levels (a pick carries it; a suggestion is worked out from entry, stop, target). */
export const rewardRisk = (i) => i.rewardRisk ?? (i.entry != null && i.stop != null && i.target != null && i.entry !== i.stop
  ? Math.abs(i.target - i.entry) / Math.abs(i.entry - i.stop) : null);
