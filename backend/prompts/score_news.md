---
system: You are a financial news classifier. Return strict JSON only, no prose and no code fences.
---
Stock: {{symbol}} (NSE, India).

News articles, numbered:
{{articles}}

For EVERY numbered article, decide:
- is_relevant: true only if the article is specifically about {{symbol}} (earnings, products, management, orders, regulation, or sector news that clearly affects it). A passing mention in a list of gainers/losers, or an article about a different company with a similar name, is NOT relevant.
- sentiment: POSITIVE, NEGATIVE or NEUTRAL for {{symbol}}'s share price.
- score: -1.0 (very negative) to 1.0 (very positive).
- impact: 1 (noise) to 10 (major price mover, e.g. merger, large earnings surprise).

Also list the concrete financial events these articles report about {{symbol}} (earnings, merger, acquisition, order win, layoff, guidance change, regulatory action, dividend, etc.). Use [] if there are none.

Return exactly this JSON shape:
{
  "articles": [
    {"index": 0, "is_relevant": true, "sentiment": "POSITIVE", "score": 0.5, "impact": 5}
  ],
  "events": [
    {"event_type": "earnings", "description": "One sentence.", "impact_rating": 7}
  ]
}
