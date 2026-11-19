"""Agreement and ranking metrics used by eval.run."""

import math


def wilson(successes: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    """Wilson score interval for a binomial proportion. None when n is 0."""
    if n <= 0:
        return None
    p = successes / n
    z2 = z * z
    denom = 1 + z2 / n
    center = (p + z2 / (2 * n)) / denom
    margin = z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / denom
    return (max(0.0, center - margin), min(1.0, center + margin))


def dcg(grades: list[int], k: int) -> float:
    total = 0.0
    for i, grade in enumerate(grades[:k]):
        total += (2**grade - 1) / math.log2(i + 2)
    return total


def ndcg_at_k(ranked: list[int], k: int, judged: list[int]) -> float:
    """Graded nDCG@k. Ideal ranking is built from every judged grade, not only the hits."""
    ideal = dcg(sorted(judged, reverse=True), k)
    if ideal == 0:
        return 1.0
    return dcg(ranked, k) / ideal


def precision_at_k(grades: list[int], k: int, relevant_at: int = 1) -> float:
    if k <= 0:
        return 0.0
    return sum(grade >= relevant_at for grade in grades[:k]) / k


def mrr(grades: list[int], relevant_at: int = 1) -> float:
    for i, grade in enumerate(grades):
        if grade >= relevant_at:
            return 1.0 / (i + 1)
    return 0.0


def mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)
