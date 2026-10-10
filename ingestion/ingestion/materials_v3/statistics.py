"""Measured pilot usage; missing provider receipts never become zero-cost evidence."""

from .contract import CandidateError, parse_json


def run_statistics(run):
    attempts = run["attempts"]
    generation = [a for a in attempts if a["receipt"].get("finish_reason") != "input_limit"]
    first = [a for a in generation if a["sequence"] == 1 and "text" in a["receipt"]]
    valid = 0
    for attempt in first:
        try:
            parse_json(attempt["receipt"]["text"])
            valid += 1
        except CandidateError:
            pass
    token_fields = ("input_tokens", "output_tokens", "reasoning_tokens", "cached_tokens")
    return {
        "attempts": len(attempts),
        "generation_attempts": len(generation),
        "successful_response_reuse_is_not_a_new_generation": True,
        "known_tokens": {
            k: sum(a["receipt"].get(k) or 0 for a in generation) for k in token_fields
        },
        "attempts_missing_token_usage": sum(
            a["receipt"].get("input_tokens") is None or a["receipt"].get("output_tokens") is None
            for a in generation
        ),
        "provider_call_seconds": sum(
            a["receipt"].get("wall_call_seconds", a["receipt"].get("seconds", 0)) for a in attempts
        ),
        "first_response_json": {
            "valid": valid,
            "denominator": len(first),
            "rate": valid / len(first) if first else None,
        },
        "syntax_repairs": sum(a["receipt"].get("repair", 0) > 0 for a in attempts),
        "length_failures": sum(a["status"] == "output_limit" for a in attempts),
        "completed_blocks": sum(s in {"validated", "empty"} for s in run["terminal"].values()),
        "cost_usd": None,
        "cost_status": "requires_frozen_rate_card_and_complete_provider_billing_receipts",
    }
