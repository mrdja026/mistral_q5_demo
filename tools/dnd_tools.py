from __future__ import annotations

from typing import TypedDict
import random


class RollResult(TypedDict):
    """Structured result for a dice roll.

    Keys:
    - notation: original NdM notation
    - count: number of dice
    - sides: number of sides per die
    - rolls: individual die results
    - total: sum of all rolls
    """

    notation: str
    count: int
    sides: int
    rolls: list[int]
    total: int


def parse_dice_notation(notation: str) -> tuple[int, int]:
    """Parse an NdM dice notation string and return (count, sides).

    Examples: "2d20" -> (2, 20). Raises ValueError for invalid input.
    """
    s = notation.lower().strip()
    if "d" not in s:
        raise ValueError("Use NdM format, e.g., '2d20'")
    count_str, sides_str = s.split("d", 1)
    count = int(count_str)
    sides = int(sides_str)
    if count <= 0 or sides <= 0:
        raise ValueError("Count and sides must be positive")
    return count, sides


def roll_dice(notation: str) -> RollResult:
    """Roll dice according to NdM notation and return a structured result."""
    count, sides = parse_dice_notation(notation)
    rolls = [random.randint(1, sides) for _ in range(count)]
    return {
        "notation": notation,
        "count": count,
        "sides": sides,
        "rolls": rolls,
        "total": sum(rolls),
    }

class AdvantageRollResult(TypedDict):
    """Structured result for a single-die roll with advantage.

    Keys:
    - notation: original dM notation
    - sides: number of sides per die (M)
    - rolls: the two raw die results
    - result: the higher of the two rolls
    - is_critical_success: True if result == 20 on a d20
    - is_critical_fail: True if result == 1 on a d20
    - message: optional message like "Critical success"/"Critical fail" or empty string
    """

    notation: str
    sides: int
    rolls: list[int]
    result: int
    is_critical_success: bool
    is_critical_fail: bool
    message: str


def roll_with_advantage(notation: str) -> AdvantageRollResult:
    """Roll a single die with advantage using dM notation (e.g., 'd20').

    Rolls twice and takes the higher result. For a d20, prints critical messages
    when the final result is a natural 20 or 1.
    """
    s = notation.lower().strip()
    if not s or "d" not in s:
        raise ValueError("Use dM format, e.g., 'd20'")

    # Accept 'd20' and also be forgiving and accept '1d20'
    if s.startswith("d"):
        sides_str = s[1:]
        if not sides_str.isdigit():
            raise ValueError("Use dM format with digits after 'd', e.g., 'd20'")
        sides = int(sides_str)
    else:
        # fallback to NdM parsing; enforce single die for advantage
        count, sides = parse_dice_notation(s)
        if count != 1:
            raise ValueError("Advantage uses a single die: use 'd20', not '2d20'")

    if sides <= 0:
        raise ValueError("Sides must be positive")

    first = random.randint(1, sides)
    second = random.randint(1, sides)
    result = max(first, second)

    is_crit_success = sides == 20 and result == 20
    is_crit_fail = sides == 20 and result == 1
    message = "Critical success" if is_crit_success else ("Critical fail" if is_crit_fail else "")

    return {
        "notation": f"d{sides}",
        "sides": sides,
        "rolls": [first, second],
        "result": result,
        "is_critical_success": is_crit_success,
        "is_critical_fail": is_crit_fail,
        "message": message,
    }


__all__ = [
    "RollResult",
    "AdvantageRollResult",
    "parse_dice_notation",
    "roll_dice",
    "roll_with_advantage",
]
