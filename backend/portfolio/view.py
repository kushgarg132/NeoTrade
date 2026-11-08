"""What a portfolio snapshot shows to a user who may or may not see verdicts."""


def mask_row(row: dict) -> dict:
    """A holding row as non-visible users see it: SELL shown as REVIEW, no score or suggestion."""
    def mask(verdict):
        return "REVIEW" if verdict in ("SELL", "REVIEW") else None

    return {**row, "verdict": mask(row.get("verdict")), "previous_verdict": mask(row.get("previous_verdict")),
            "verdict_since": None, "score": None, "suggested": None}


def present(snapshot: dict, show_verdicts: bool) -> dict:
    snapshot = {k: v for k, v in snapshot.items() if k not in ("_id", "raw_holdings")}
    snapshot["verdicts_visible"] = show_verdicts
    if show_verdicts:
        return snapshot
    snapshot["plan"] = None  # sell / add suggestions: same audience as the verdicts

    snapshot["holdings"] = [mask_row(row) for row in snapshot.get("holdings", [])]
    return snapshot
