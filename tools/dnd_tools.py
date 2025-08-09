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
    """Parse dice notation and return (count, sides).

    Accepts standard NdM (e.g., "2d20") and the common shorthand "d20" which
    defaults to a single die (1d20). Raises ValueError for invalid input.
    """
    s = notation.lower().strip()
    if "d" not in s:
        raise ValueError("Use NdM format (e.g., '2d20') or shorthand 'd20'")
    count_str, sides_str = s.split("d", 1)
    if not sides_str.isdigit():
        raise ValueError("Number of sides must be digits after 'd', e.g., 'd20'")
    sides = int(sides_str)
    if count_str == "":
        count = 1  # allow 'd20' shorthand
    else:
        if not count_str.isdigit():
            raise ValueError("Number of dice must be digits before 'd', e.g., '2d6'")
        count = int(count_str)
    if count <= 0 or sides <= 0:
        raise ValueError("Count and sides must be positive")
    return count, sides


def roll_dice(notation: str) -> RollResult:
    """Roll dice according to NdM or shorthand 'dM' and return a structured result."""
    count, sides = parse_dice_notation(notation)
    rolls = [random.randint(1, sides) for _ in range(count)]
    return {
        "notation": f"{count}d{sides}",
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


class DisadvantageRollResult(TypedDict):
    """Structured result for a single-die roll with disadvantage using dM notation.

    Keys mirror AdvantageRollResult but the selected result is the lower of the two.
    """

    notation: str
    sides: int
    rolls: list[int]
    result: int
    is_critical_success: bool
    is_critical_fail: bool
    message: str


def roll_with_disadvantage(notation: str) -> DisadvantageRollResult:
    """Roll a single die with disadvantage using dM notation (e.g., 'd20')."""
    s = notation.lower().strip()
    if not s or "d" not in s:
        raise ValueError("Use dM format, e.g., 'd20'")

    if s.startswith("d"):
        sides_str = s[1:]
        if not sides_str.isdigit():
            raise ValueError("Use dM format with digits after 'd', e.g., 'd20'")
        sides = int(sides_str)
    else:
        count, sides = parse_dice_notation(s)
        if count != 1:
            raise ValueError("Disadvantage uses a single die: use 'd20', not '2d20'")

    if sides <= 0:
        raise ValueError("Sides must be positive")

    first = random.randint(1, sides)
    second = random.randint(1, sides)
    result = min(first, second)

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


class DamageRollResult(TypedDict):
    """Structured result for a damage roll.

    Keys:
    - notation: NdM provided
    - rolls: individual die results
    - total: sum of rolls (after crit multiplier if applied by caller)
    - crit_multiplier: multiplier applied to base roll total (1 or 2 typically)
    """

    notation: str
    rolls: list[int]
    total: int
    crit_multiplier: int


def roll_damage(notation: str, crit_multiplier: int = 1) -> DamageRollResult:
    """Roll damage using NdM notation. Caller decides crit multiplier (1=normal, 2=crit)."""
    base = roll_dice(notation)
    total = int(base["total"]) * int(max(1, crit_multiplier))
    return {
        "notation": base["notation"],
        "rolls": base["rolls"],
        "total": total,
        "crit_multiplier": int(max(1, crit_multiplier)),
    }


__all__ = [
    "RollResult",
    "AdvantageRollResult",
    "DisadvantageRollResult",
    "DamageRollResult",
    "parse_dice_notation",
    "roll_dice",
    "roll_with_advantage",
    "roll_with_disadvantage",
    "roll_damage",
]
