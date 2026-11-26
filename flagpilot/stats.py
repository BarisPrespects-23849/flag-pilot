"""Chi-square goodness of fit, for the sample-ratio-mismatch check."""

import math


def chi_square_survival(statistic: float, df: int) -> float:
    """P(X >= statistic) for a chi-square variable with integer degrees of freedom."""
    if df < 1:
        raise ValueError("df must be at least 1")
    half = max(statistic, 0.0) / 2
    if df % 2 == 0:
        return math.exp(-half) * sum(half**i / math.factorial(i) for i in range(df // 2))
    tail = sum(half ** (i - 0.5) / math.gamma(i + 0.5) for i in range(1, (df - 1) // 2 + 1))
    return math.erfc(math.sqrt(half)) + math.exp(-half) * tail


def srm_p_value(observed: dict[str, int], weights: dict[str, float]) -> float:
    """p-value that the observed arm counts came from the configured split."""
    total_weight = sum(weights.values())
    total = sum(observed.get(arm, 0) for arm in weights)
    if total_weight <= 0 or total <= 0:
        raise ValueError("Need a configured split and at least one exposure.")
    if any(observed.get(arm, 0) and not weight for arm, weight in weights.items()):
        return 0.0  # traffic reached an arm configured to get none
    expected = {arm: total * w / total_weight for arm, w in weights.items() if w > 0}
    if len(expected) < 2:
        return 1.0
    statistic = sum((observed.get(arm, 0) - e) ** 2 / e for arm, e in expected.items())
    return chi_square_survival(statistic, len(expected) - 1)
