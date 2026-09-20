"""The wizard's sign-in step rejoins a sign-in that is already running.

Purpose    : `POST /api/auth/google/start` answers 409 with the job_id of the
             run already in progress rather than opening a second Chrome.
             api.js used to drop that body, so a caller could report the
             conflict and nothing else (CR-C-E10 F1). This pins that the id
             survives the error and that the step polls that exact job.
Constraints: Nothing real is started: both auth routes are intercepted, so no
             browser launches and no provider is contacted.
Ticket     : P2-E11-W4-S1-T7.
"""

from __future__ import annotations

import json

import pytest

from .conftest import SEEDED_COMPLETED_AT

pytestmark = pytest.mark.asyncio(loop_scope="session")

RUNNING_JOB = "job-already-running"


async def _set_completed_at(page, base_url, value):
    await page.request.post(
        base_url + "/api/settings/onboarding.completed_at",
        data=json.dumps({"value": value}),
        headers={"Content-Type": "application/json"},
    )


async def _set_last_step(page, base_url, value):
    await page.request.post(
        base_url + "/api/settings/onboarding.last_step",
        data=json.dumps({"value": value}),
        headers={"Content-Type": "application/json"},
    )


async def test_a_409_rejoins_the_running_sign_in(page, base_url):
    polled: list[str] = []

    async def conflict(route):
        await route.fulfill(
            status=409,
            content_type="application/json",
            body=json.dumps(
                {"detail": "A Google sign-in is already in progress.", "job_id": RUNNING_JOB}
            ),
        )

    async def progress(route):
        polled.append(route.request.url)
        await route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"state": "waiting_for_user", "message": "in the Chrome window"}),
        )

    await _set_completed_at(page, base_url, None)
    try:
        await _set_last_step(page, base_url, "signin")
        await page.route("**/api/auth/google/start", conflict)
        await page.route("**/api/auth/google/progress*", progress)
        await page.goto(base_url + "/#/setup")
        await page.wait_for_selector("#fp-setup-signin-status", timeout=15000)

        await page.get_by_role("button", name="Sign in with Google").click()
        await page.wait_for_function(
            "() => document.getElementById('fp-setup-signin-status')"
            ".textContent.includes('Waiting')",
            timeout=15000,
        )

        assert polled, "the conflict was reported but the running job was never rejoined"
        assert RUNNING_JOB in polled[0]
    finally:
        await _set_completed_at(page, base_url, SEEDED_COMPLETED_AT)
        await _set_last_step(page, base_url, None)
