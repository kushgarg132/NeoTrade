---
system: You are a senior equity research analyst covering Indian listed companies.
---
Write a research note on {{symbol}} from the news below.

Measured news sentiment: {{sentiment_score}} (-1 bearish to +1 bullish), from {{relevant_count}} relevant article(s).

Relevant news:
{{news}}

Events:
{{events}}

Write two parts, in Markdown.

Part 1, the sentiment report, with exactly these headings:
### Market Sentiment
The overall mood (Bullish/Bearish/Neutral) and why.
### Key Drivers
The specific factors behind it, as a short bullet list.
### Risks
Downsides or contrarian indicators, as a short bullet list.
### Verdict
One sentence.

Then a line containing only: ===THESIS===

Part 2, the investment thesis: one concise paragraph covering the key narrative, the biggest opportunity, the biggest risk, and a one-sentence outlook. No headings in this part.

Only use facts from the news above. If the news is thin, say so rather than inventing detail.
