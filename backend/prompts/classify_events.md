---
system: You are a financial event detector. Return strict JSON.
---
Extract financial events from the following text:
"{{text}}"

Events to look for: Earnings, Mergers, Acquisitions, Layoffs, Guidance Change, FDA Approval, etc.

Return a JSON list of objects:
[{ "event_type": "...", "description": "...", "symbols": ["AAPL"], "impact_rating": 1-10 }]

If no events found, return [].
