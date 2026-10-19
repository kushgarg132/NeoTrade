"""Short AI summaries shown as cards ("AI summary" + as-of time): Home's "Your day",
a note under each holding action, AI Activity's "what the AI did today", the weekly
report's paragraph and the Journal's "what your trades say".

Every summary is written by a job at a fixed cadence and stored in Mongo
`ai_summaries` (one doc per user, kind and period key). The read endpoints
(routers/summaries.py) only read; a page open never calls a model."""
