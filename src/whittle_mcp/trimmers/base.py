from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Trim:
    text: str                     # what the agent should read
    omitted_lines: int = 0        # original lines replaced by markers
    notes: list[str] = field(default_factory=list)
    changed: bool = True          # False when the input was returned as it came (unknown format, already small)
