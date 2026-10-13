"""Deterministic source start anchors, never model-generated character positions."""

import re


def source_spans(block):
    text = block["text"]
    pattern = r"\n+" if block.get("kind") == "table" else r"(?<=[.!?])\s+"
    cuts = [0, *[m.end() for m in re.finditer(pattern, text)], len(text)]
    return [
        {"id": f"S{i}", "start": start, "end": end}
        for i, (start, end) in enumerate(zip(cuts, cuts[1:]))
        if start < end
    ]


def annotated_text(block):
    """Insert IDs in the prompt only; validator and documents retain raw text."""
    return "".join(
        f"[{span['id']}]" + block["text"][span["start"] : span["end"]]
        for span in source_spans(block)
    )
