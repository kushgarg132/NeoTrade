---
system: You are a strict JSON output generator.
---
Company: "{{name}}" (ticker {{symbol}}).
List up to 5 peer/competitor tickers in the same sector.
Return ONLY a valid JSON array of strings, e.g. ["PEER1", "PEER2"]. If unsure, return [].
