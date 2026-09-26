"""Browser test for UAT7-N09: the Telegram tab's two <ul>s used purely as
layout (current-targets chips, found-chat rows) kept the UA stylesheet's
disc bullets and 40px padding-inline-start.

Split into its own file rather than added to test_alerts_telegram_targets.py,
which was already at this suite's 300-line file cap.
"""

from __future__ import annotations

import pytest

from .conftest import open_alerts_tab

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_telegram_target_lists_have_no_default_bullet_indent(page, base_url):
    """Both lists render regardless of visibility (getComputedStyle resolves
    fixed-length properties like padding even while `hidden` is set), so no
    Telegram bot needs to be configured to check this."""
    await open_alerts_tab(page, base_url)
    for list_id in ("fp-tg-current-targets", "fp-tg-chats-list"):
        style = await page.evaluate(
            """(id) => {
                const s = getComputedStyle(document.getElementById(id));
                return { padding: s.paddingInlineStart, listStyle: s.listStyleType };
            }""",
            list_id,
        )
        assert style["padding"] == "0px", f"#{list_id} kept its UA list padding"
        assert style["listStyle"] == "none", f"#{list_id} kept its UA bullet"
