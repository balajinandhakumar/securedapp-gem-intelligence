"""
Regression tests for the Windows event-loop policy bug in the direct GeM
collector.

Root cause (reproduced live): uvicorn installs
``asyncio.WindowsSelectorEventLoopPolicy`` process-wide on Windows
(``uvicorn/loops/asyncio.py``). Playwright's sync API builds its own event loop
with ``asyncio.new_event_loop()``, which honours that policy, so it got a
SelectorEventLoop. A SelectorEventLoop cannot spawn subprocesses on Windows and
``asyncio.base_events._make_subprocess_transport`` raises a bare
``NotImplementedError`` the instant the browser is launched -- surfacing as
``NO_RECORDS`` with ``<url>: NotImplementedError:``.

These tests pin the fix: the collector's Playwright loop is created under the
Proactor policy (``windows_proactor_loop_policy``) and the host policy is
restored afterwards. No browser is launched and no GeM request is made.
"""
from __future__ import annotations

import asyncio
import sys

import pytest

from app.services.ingestion.gem_public_collector import (
    open_listing_session,
    windows_proactor_loop_policy,
)

windows_only = pytest.mark.skipif(
    sys.platform != "win32", reason="Windows event loop policy behaviour"
)


def _set_selector_policy():
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@windows_only
def test_selector_loop_cannot_spawn_subprocess_but_helper_can():
    """
    The exact failure: a SelectorEventLoop (what uvicorn forces) cannot open a
    subprocess, while a loop created under the helper can -- which is what
    Playwright needs to launch Chromium.
    """
    original = asyncio.get_event_loop_policy()
    try:
        _set_selector_policy()

        selector_loop = asyncio.new_event_loop()
        try:
            with pytest.raises(NotImplementedError):
                selector_loop.run_until_complete(
                    asyncio.create_subprocess_exec(sys.executable, "-c", "pass")
                )
        finally:
            selector_loop.close()

        with windows_proactor_loop_policy():
            loop = asyncio.new_event_loop()
        try:
            assert isinstance(loop, asyncio.ProactorEventLoop)
            proc = loop.run_until_complete(
                asyncio.create_subprocess_exec(sys.executable, "-c", "pass")
            )
            assert loop.run_until_complete(proc.wait()) == 0
        finally:
            loop.close()
    finally:
        asyncio.set_event_loop_policy(original)


@windows_only
def test_helper_restores_the_host_event_loop_policy():
    original = asyncio.get_event_loop_policy()
    try:
        selector_policy = asyncio.WindowsSelectorEventLoopPolicy()
        asyncio.set_event_loop_policy(selector_policy)
        with windows_proactor_loop_policy():
            assert isinstance(asyncio.get_event_loop_policy(), asyncio.WindowsProactorEventLoopPolicy)
        assert asyncio.get_event_loop_policy() is selector_policy
    finally:
        asyncio.set_event_loop_policy(original)


@windows_only
def test_helper_is_a_noop_when_proactor_is_already_active():
    original = asyncio.get_event_loop_policy()
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        with windows_proactor_loop_policy():
            assert isinstance(asyncio.get_event_loop_policy(), asyncio.WindowsProactorEventLoopPolicy)
        assert isinstance(asyncio.get_event_loop_policy(), asyncio.WindowsProactorEventLoopPolicy)
    finally:
        asyncio.set_event_loop_policy(original)


@windows_only
def test_open_listing_session_starts_playwright_under_the_proactor_policy(monkeypatch):
    """
    ``open_listing_session`` must create Playwright's loop while the Proactor
    policy is in force, even when the process (like a uvicorn server) has the
    Selector policy installed.
    """
    import playwright.sync_api as psa

    observed: dict = {}

    class _StopHere(Exception):
        pass

    def fake_sync_playwright():
        observed["policy"] = asyncio.get_event_loop_policy()
        raise _StopHere()

    monkeypatch.setattr(psa, "sync_playwright", fake_sync_playwright)

    original = asyncio.get_event_loop_policy()
    try:
        _set_selector_policy()
        with pytest.raises(_StopHere):
            open_listing_session("https://bidplus.gem.gov.in/all-bids", timeout_ms=1000)
    finally:
        asyncio.set_event_loop_policy(original)

    assert isinstance(observed["policy"], asyncio.WindowsProactorEventLoopPolicy)
