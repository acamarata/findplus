"""Does a provider need the person right now? One field for every surface.

Purpose    : Lost sign-in (spec in-app-login.md §6). GET /api/auth/status and
             /api/status carry `attention` per provider so the tray, the native
             banner, the dashboard banner, the wizard and `findplus auth` read
             the same answer: "reauth" (sign in again), "unlock" (unlock the
             encrypted locations) or "none". Also says which findplus:// deep
             link may open a login right now: only one whose provider needs it.
Inputs     : the stored Google session marks (bootstrap.py, revoked.py) and the
             saved Apple session plus its "Apple refused it" marker (auth.py).
Outputs    : attention_for(); deep_link_for(); deep_links(); deep_link_allowed().
Constraints: Never raises (a broken probe answers "none"); no network, no DB;
             a provider that was never signed in needs no attention (the card's
             Connect button covers it, not a lost-sign-in banner).
"""

from __future__ import annotations

GOOGLE = "google-find-hub"
APPLE = "apple-find-my"
ATTENTION_VALUES = ("reauth", "unlock", "none")

SIGNIN_GOOGLE = "findplus://signin/google"
UNLOCK_GOOGLE = "findplus://unlock/google"
SIGNIN_APPLE = "findplus://signin/apple"
_LINKS = {
    (GOOGLE, "reauth"): SIGNIN_GOOGLE,
    (GOOGLE, "unlock"): UNLOCK_GOOGLE,
    (APPLE, "reauth"): SIGNIN_APPLE,
}


def _google() -> str:
    from .google_findhub.bootstrap import is_session_revoked, needs_shared_key, stored_account_email

    if stored_account_email() and is_session_revoked():
        return "reauth"  # Google refused the saved login (revoked.py set the mark)
    if needs_shared_key():
        return "unlock"  # signed in, but a key reset left the locations locked
    return "none"


def _apple() -> str:
    from findplus.config import get_settings

    from .apple_findmy.auth import auth_required_marked, is_signed_in, read_saved_state

    settings = get_settings()
    data = read_saved_state(settings)
    if data is None:
        return "none"  # never signed in, or signed out on purpose
    if not is_signed_in(data) or auth_required_marked(settings):
        return "reauth"
    return "none"


def attention_for(provider: str) -> str:
    """One provider's attention: "reauth", "unlock" or "none". Never raises."""
    try:
        if provider == GOOGLE:
            return _google()
        if provider == APPLE:
            return _apple()
    except Exception:
        return "none"
    return "none"


def deep_link_for(provider: str, attention: str) -> str | None:
    """The deep link that fixes this provider's attention, or None."""
    return _LINKS.get((provider, attention))


def deep_links(attention: dict[str, str]) -> dict[str, bool]:
    """Each supported deep link, and whether it may open a login right now."""
    live = {deep_link_for(p, a) for p, a in attention.items()}
    return {url: url in live for url in (SIGNIN_GOOGLE, UNLOCK_GOOGLE, SIGNIN_APPLE)}


def deep_link_allowed(url: str) -> bool:
    """True only while the provider this link is for needs exactly that fix."""
    for (provider, attention), link in _LINKS.items():
        if link == url:
            return attention_for(provider) == attention
    return False
