"""
Port de trend.ts (Cortex) — régression linéaire sur l'historique de scores.
"""

from typing import Literal

TrendSignal = Literal["degrading", "improving", "stable", "insufficient_data"]


def compute_degradation_slope(scores: list[float]) -> float:
    """
    Régression linéaire simple (moindres carrés) sur les points (i, score[i]).
    Retourne la pente : > 0.5 = dégradation, < -0.5 = amélioration, 0 si < 3 points.
    """
    n = len(scores)
    if n < 3:
        return 0.0

    sum_x  = sum(range(n))
    sum_y  = sum(scores)
    sum_xy = sum(i * scores[i] for i in range(n))
    sum_x2 = sum(i * i for i in range(n))

    denom = n * sum_x2 - sum_x * sum_x
    if denom == 0:
        return 0.0

    return (n * sum_xy - sum_x * sum_y) / denom


def get_trend_signal(slope: float) -> TrendSignal:
    if slope == 0.0:
        return "insufficient_data"
    if slope > 0.5:
        return "degrading"
    if slope < -0.5:
        return "improving"
    return "stable"
