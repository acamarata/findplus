"""Spec 6.4 test vectors V1 to V6 against the pure scorer."""

from __future__ import annotations

from findplus.quality import rules as r
from findplus.quality.score import score_series
from tests.quality._vectors import (
    fix,
    v1_owner_case,
    v2_real_drive,
    v3_school_run,
    v4_two_bad_in_a_row,
)


def test_v1_owner_case_flags_the_middle_fix() -> None:
    out = score_series(v1_owner_case())
    assert out[2].suspect and r.ABA_TELEPORT in out[2].reasons
    assert out[2].score == 0.2
    assert not out[1].suspect and not out[3].suspect
    assert out[1].reasons == () and out[3].reasons == ()


def test_v2_real_drive_flags_nothing() -> None:
    out = score_series(v2_real_drive())
    assert all(s.reasons == () and s.score == 1.0 for s in out.values())


def test_v3_school_run_flags_nothing() -> None:
    out = score_series(v3_school_run())
    assert all(s.reasons == () for s in out.values())


def test_v4_two_bad_in_a_row_are_kept_and_scored_point_six() -> None:
    out = score_series(v4_two_bad_in_a_row())
    assert not any(s.suspect for s in out.values())
    assert out[2].score == 0.6 and out[3].score == 0.6
    assert out[2].corroborated_by == 3 and out[3].corroborated_by == 2


def test_v5_sibling_disagree_flags_the_bag() -> None:
    # Shoes and watch at school; the bag has sat still since 8:10 and now reports 3 km away.
    school = 3000
    shoes = [fix(10, 0, school), fix(11, 4, school, 5)]
    watch = [fix(20, 1, school, -4), fix(21, 5, school)]
    bag = [fix(30, -110, school), fix(31, -60, school), fix(32, 2, school + 3000)]
    out = score_series(bag, siblings={"shoes": shoes, "watch": watch})
    assert out[32].suspect and r.SIBLING_DISAGREE in out[32].reasons
    assert not out[30].suspect and not out[31].suspect


def test_v5_one_sibling_is_not_enough() -> None:
    school = 3000
    bag = [fix(30, -60, school), fix(32, 2, school + 3000)]
    out = score_series(bag, siblings={"shoes": [fix(10, 0, school)]})
    assert not out[32].suspect


def test_v5_a_tracker_that_was_moving_may_be_carried_away() -> None:
    school = 3000
    bag = [fix(29, -20, 0), fix(30, -10, 1500), fix(32, 2, school + 3000)]
    sibs = {"a": [fix(10, 0, school)], "b": [fix(20, 1, school, 3)]}
    assert not score_series(bag, siblings=sibs)[32].suspect


def test_v6_corroborated_jump_is_rescued() -> None:
    fixes = [fix(1, 0), fix(2, 1, 2500), fix(3, 3, 2560, acc=30), fix(4, 40, 2500)]
    out = score_series(fixes)
    assert not out[2].suspect
    assert out[2].score == 0.6 and out[2].corroborated_by == 3
    assert r.JUMP_UNCONFIRMED in out[2].reasons


def test_a_stray_in_a_row_with_a_sibling_voucher_is_rescued() -> None:
    fixes = v1_owner_case()
    near_b = {"watch": [fix(50, 1.5, 2500, 20)]}
    out = score_series(fixes, siblings=near_b)
    assert not out[2].suspect and out[2].corroborated_by == 50


def test_unconfirmed_jump_is_suspect_until_a_next_fix_exists() -> None:
    from tests.quality._vectors import T0

    fixes = [fix(1, 0), fix(2, 1, 2500)]
    held = score_series(fixes, now=T0)
    assert held[2].suspect and held[2].reasons == (r.JUMP_UNCONFIRMED,)
    assert held[2].score == 0.4
    confirmed = score_series([*fixes, fix(3, 2, 2520)], now=T0)
    assert not confirmed[2].suspect
    continued = score_series([*fixes, fix(3, 2, 5000)], now=T0)
    assert continued[2].reasons == ()


def test_an_old_unconfirmed_jump_is_not_held_forever() -> None:
    from datetime import timedelta

    from tests.quality._vectors import T0

    held = score_series([fix(1, 0), fix(2, 1, 2500)], now=T0 + timedelta(hours=2))
    assert not held[2].suspect


def test_soft_reasons_never_make_a_fix_suspect_alone() -> None:
    from datetime import timedelta

    loose = fix(1, 0, acc=2500)
    skewed = fix(2, 1, fetched_at=fix(2, 1).t - timedelta(minutes=10))
    out = score_series([loose, skewed])
    assert out[1].reasons == (r.LOW_ACCURACY,) and out[1].score == 0.5 and not out[1].suspect
    assert out[2].reasons == (r.CLOCK_SKEW,) and out[2].score == 0.8


def test_own_reports_get_a_capped_bonus() -> None:
    from datetime import timedelta

    skewed = fix(1, 0, own_report=True, fetched_at=fix(1, 0).t - timedelta(minutes=10))
    assert score_series([skewed])[1].score == 0.88
    assert score_series([fix(2, 0, own_report=True)])[2].score == 1.0
