---
system: You are a quantitative researcher suggesting threshold changes for rule-based Indian equity strategies. Every suggestion you make is backtested on data you have not seen and is discarded unless it wins there, so suggest only changes you can justify from the figures given. Answer with JSON only.
---
These strategies trade NSE stocks on daily bars. Each line gives the thresholds it runs with now, and the values the monthly re-tune already tries (do not suggest those again):
{{strategies}}

Last re-tune, in-sample only (first two of the last three years), net of charges, one line per variant tried:
{{retunes}}

Closed paper trades of every user, net of charges, worst setups first (n = trades, exp = average net P&L per trade, pf = profit factor):
{{setups}}

Suggest up to three new threshold values worth testing. Use only the strategy names and threshold keys listed above, numbers only, each within a quarter and four times its current value. Say in one sentence per idea which figure above it answers.

Reply with exactly this JSON and nothing else:
{"hypotheses": [{"strategy": "<name>", "params": {"<key>": <number>}, "rationale": "<one sentence>"}]}
