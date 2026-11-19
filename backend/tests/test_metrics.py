import math

import pytest

from eval.linking import Candidate, decide, stratum_of_linked
from eval.metrics import mrr, ndcg_at_k, precision_at_k, wilson


def test_wilson_empty_and_perfect():
    assert wilson(0, 0) is None
    low, high = wilson(1, 1)
    assert low == pytest.approx(0.2065, abs=1e-3)
    assert high == 1.0


def test_ndcg_penalizes_a_missed_relevant_document():
    # Ranked gains: 3, 0, 1. Ideal gains from judgments [2, 1, 0]: 3 + 1/log2(3).
    score = ndcg_at_k([2, 0, 1], 3, [2, 1, 0])
    ideal = 3 + 1 / math.log2(3)
    assert score == pytest.approx(3.5 / ideal)


def test_ndcg_is_perfect_when_nothing_is_relevant():
    assert ndcg_at_k([0, 0], 5, [0, 0]) == 1.0


def test_precision_and_mrr_treat_short_lists_as_misses():
    assert precision_at_k([2, 0, 1], 5) == 0.4
    assert mrr([0, 0, 2]) == pytest.approx(1 / 3)
    assert mrr([0, 0]) == 0.0


def test_stratum_priority_matches_the_plan():
    assert stratum_of_linked(common=True, has_institution=False, tier="loose", method="keywords", score=30) == "common_name"
    assert stratum_of_linked(common=False, has_institution=False, tier="exact", method="keywords", score=25) == "no_institution"
    assert stratum_of_linked(common=False, has_institution=True, tier="loose", method="keywords", score=25) == "loose_name"
    assert stratum_of_linked(common=False, has_institution=True, tier="exact", method="name", score=3) == "name_unique"
    assert stratum_of_linked(common=True, has_institution=True, tier="exact", method="name", score=3) == "common_name"
    assert stratum_of_linked(common=False, has_institution=True, tier="exact", method="semantic", score=0.98) == "semantic"
    assert stratum_of_linked(common=False, has_institution=True, tier="exact", method="keywords", score=10) == "keywords_borderline"
    assert stratum_of_linked(common=False, has_institution=True, tier="exact", method="keywords", score=20) == "keywords_high"
    assert stratum_of_linked(common=False, has_institution=True, tier="exact", method="keywords", score=9) is None


def test_decide_follows_the_linker_margin_and_semantic_fallback():
    close = [Candidate(1, "exact", 15, False, None), Candidate(2, "exact", 12, False, None)]
    clear = [Candidate(1, "exact", 30, False, None), Candidate(2, "exact", 12, False, None)]
    assert decide(close, 10, 20, 20, 1.5, 0.97, True) is None
    assert decide(clear, 10, 20, 20, 1.5, 0.97, True) == 1

    semantic = [Candidate(1, "exact", 5, True, 0.99)]
    assert decide(semantic, 10, 20, 20, 1.5, 0.97, True) == 1
    assert decide(semantic, 10, 20, 20, 1.5, 0.995, True) is None
    both = [Candidate(1, "exact", 0, True, 0.99), Candidate(2, "exact", 0, True, 0.98)]
    assert decide(both, 10, 20, 20, 1.5, 0.97, True) is None

    # A rare, unique name that fails the topic test is still linked; a lone common name falls back to semantic.
    name_only = [Candidate(1, "exact", 0, True, 0.5, True)]
    assert decide(name_only, 10, 20, 20, 1.5, 0.97, True) == 1
    assert decide(name_only, 10, 20, 20, 1.5, 0.97, False) is None
    common = [Candidate(1, "exact", 0, True, 0.5, False)]
    assert decide(common, 10, 20, 20, 1.5, 0.97, True) is None

    loose_outside = [Candidate(1, "loose", 40, False, None)]
    assert decide(loose_outside, 10, 20, 20, 1.5, 0.97, False) is None
