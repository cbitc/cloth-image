"""面料图颜色重排的纯函数单测（不涉及网络）。"""

from __future__ import annotations

import pytest

from app.abilities.base import MaterialImageResult
from app.abilities.color_ops import hex_to_lab
from app.abilities.material_search.rerank import (
    COLOR_WEIGHT,
    MISSING_COLOR_SCORE,
    color_score,
    rank_prior,
    score_candidates,
    target_labs,
)


def _result(url: str) -> MaterialImageResult:
    return MaterialImageResult(label="棉", external_url=url)


def test_target_labs_normalizes_palette_weights() -> None:
    targets = target_labs(
        [
            {"hex": "#000000", "ratio": 3.0},
            {"hex": "#FFFFFF", "ratio": 1.0},
        ]
    )
    assert len(targets) == 2
    assert targets[0][1] == pytest.approx(0.75)
    assert targets[1][1] == pytest.approx(0.25)


def test_target_labs_falls_back_to_dominant_hex() -> None:
    targets = target_labs([], "#1B2A4A")
    assert len(targets) == 1
    assert targets[0][1] == pytest.approx(1.0)


def test_target_labs_is_empty_without_any_usable_colour() -> None:
    assert target_labs([], "") == []
    assert target_labs([{"hex": "nope"}], "also-nope") == []
    assert target_labs([{"hex": "#000000"}], "")[0][1] == pytest.approx(
        1.0
    )  # 权重缺失→均分


def test_color_score_is_one_for_an_exact_match() -> None:
    lab = hex_to_lab("#1B2A4A")
    assert lab is not None
    assert color_score([(lab, 1.0)], [(lab, 1.0)]) == pytest.approx(1.0)


def test_color_score_is_none_without_colour_information() -> None:
    lab = hex_to_lab("#1B2A4A")
    assert lab is not None
    assert color_score(None, [(lab, 1.0)]) is None
    assert color_score([(lab, 1.0)], []) is None


def test_score_candidates_promotes_the_matching_colour() -> None:
    target = hex_to_lab("#1B2A4A")
    other = hex_to_lab("#F5F0DC")
    assert target is not None and other is not None

    candidates = [
        (_result("https://example.com/first"), [(other, 1.0)]),
        (_result("https://example.com/second"), [(target, 1.0)]),
    ]
    scored = score_candidates(candidates, [(target, 1.0)])

    assert [item.external_url for item, _ in scored] == [
        "https://example.com/second",
        "https://example.com/first",
    ]
    assert scored[0][1] > scored[1][1]


def test_uninspected_candidates_stay_mid_pack() -> None:
    target = hex_to_lab("#1B2A4A")
    other = hex_to_lab("#F5F0DC")
    assert target is not None and other is not None

    candidates = [
        (_result("https://example.com/uninspected"), None),
        (_result("https://example.com/match"), [(target, 1.0)]),
        (_result("https://example.com/mismatch"), [(other, 1.0)]),
    ]
    order = [
        item.external_url for item, _ in score_candidates(candidates, [(target, 1.0)])
    ]

    assert order[0].endswith("/match")
    assert order[1].endswith("/uninspected")
    assert order[2].endswith("/mismatch")


def test_uninspected_score_blends_neutral_colour_with_rank_prior() -> None:
    target = hex_to_lab("#1B2A4A")
    assert target is not None

    candidates = [
        (_result("https://example.com/a"), None),
        (_result("https://example.com/b"), None),
    ]
    scored = score_candidates(candidates, [(target, 1.0)])

    expected = round(
        COLOR_WEIGHT * MISSING_COLOR_SCORE + (1 - COLOR_WEIGHT) * rank_prior(0, 2), 2
    )
    assert scored[0][1] == pytest.approx(expected)
    assert scored[0][1] <= 1.0
