# Interactive AI cards

Date: 2026-11-02. Owner request: "All the AI summary cards and texts are very boring in the UI. I
want to make them interactive." The owner chose all four options below.

All of this lives in one shared component, `frontend/src/components/ai/AiSummary.jsx`
(`AiMarkdown`, `AiCard`, `AiSummary`, `AiLabel`), with its parsing in
`frontend/src/utils/aiMarkdown.js`. Every AI card gets it: AI → Activity, Money → Journal,
Weekly report, Money overview, Home brief, Market today, Index, Idea detail, and Stock AI read.

1. **Tappable stocks and numbers.**
   - Ticker detection: `aiMarkdown.js::tickerCandidates` takes ALL-CAPS words of at least 3
     characters, minus a stoplist of market words, up to 8 per text. One `/market/quotes` call
     per text checks them.
   - Only names that return a quote become chips (`StockChip`): the symbol plus its day %,
     linking to `/stock/:symbol`.
   - Signed percents and ₹ amounts take the gain or loss tone. Amounts keep the `private` mask.
2. **Key points first.**
   - `aiMarkdown.js::outline` splits a text into a `lead`, an `intro` and `sections`.
   - The `lead` is the first paragraph or up to 3 list items, shown in an `--accent-soft` box
     titled "Key points" (or the text's first heading).
   - Each later heading becomes a `<details>` section.
   - "Read more" stays only for long texts with no headings.
3. **Ask a follow-up.**
   - `aiMarkdown.js::followUps` builds 2–3 question chips with no model call: "Why SYMBOL?" for
     the first two stocks, plus "What should I do now?" or "What does this mean for me?", and
     "Explain this simply".
   - A chip fires `margin-note:ask`. `ChatWidget` opens and sends the question, with the card's
     title and text (first 4,000 characters) as a prior assistant turn in `history`. The
     server's `context` only takes slug-shaped values, so the text cannot go there.
   - Chips appear only on texts with at least 2 paragraphs or items. They are off for
     line-clamped previews until opened, for streaming text, and for secondary texts on the
     same page.
4. **Motion and polish** (CSS only, per DESIGN.md; off under `prefers-reduced-motion`):
   - `.ai-card` draws a 2 px accent rail;
   - the "AI summary" label gets a Sparkles icon;
   - `.ai-rise` fades blocks in and up over 220 ms, staggered 40 ms each, on mount;
   - chips use `.tap`.
   - The typewriter effect was skipped: it would replay on every visit.

Not changed: backend prompts and data. Tests: `frontend/src/utils/aiMarkdown.test.js` covers
the tickers, tones, outline and follow-ups.
