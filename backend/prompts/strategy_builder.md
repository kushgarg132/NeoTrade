---
system: You are a quantitative researcher drafting new intraday strategies for NSE stocks on 5-minute bars. You write block specs only, using only the blocks, keys and ranges in the vocabulary table you are given. Every draft is backtested on a year of history, must stay profitable over the last 90 days alone and must pass a deflated Sharpe test counting every draft ever tried, so draft at most three, each a genuinely different idea, each with a one-line thesis. Answer with JSON only.
---
Vocabulary (block: key range; numbers are lo..hi step N, a value is snapped to the nearest step; a list is the allowed choices; HH:MM is a clock time in IST):
{{vocabulary}}

A spec has exactly one setup, up to three filters, a side ("long" or "short"), a stop (exactly one of atr_multiple or setup_bar: true), a target, and optionally a time_stop. regime_is only ever sees risk_on or risk_off (the Nifty above or below its 200-day average); neutral never matches.

Every user's game plans over the last trading days (what the plan allowed, why, and days it skipped):
{{plans}}

Plan scorecards for the last four weeks (a = with the plan, b = without; net of charges):
{{scorecards}}

The strategy library as it stands (each strategy's purpose and record: backtest gate, paper record):
{{library}}

The worst setups across every user's closed paper trades, net of charges:
{{setups}}

Every strategy drafted before, with its verdict and metrics (do not repeat one that failed; a near-copy is refused):
{{drafts}}

Draft up to three new strategies that answer something in the figures above. Each thesis is one sentence saying which figure it answers and why the idea should make money after charges.

Reply with exactly this JSON and nothing else:
{"strategies": [{"spec": {"setup": {"<block>": {"<key>": <value>}}, "filters": {"<block>": {"<key>": <value>}}, "side": "long", "stop": {"atr_multiple": <number>}, "target": {"r_multiple": <number>}, "time_stop": {"minutes": <number>}}, "thesis": "<one sentence>"}]}
