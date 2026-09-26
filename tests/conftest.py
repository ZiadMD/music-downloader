"""Shared pytest fixtures.

Tkinter is a shared global resource: ``ttkbootstrap`` binds its ``Style`` to
the first live root and refuses a second one, and a destroyed root takes the
Tcl interpreter's font database with it. So the whole suite gets exactly one
root, created once per session, and no test may destroy it.
"""

import tkinter as tk

import pytest


@pytest.fixture(scope="session")
def tk_root():
    """The one and only Tk root for the test session.

    Skips the tests that need it when there is no display, rather than failing
    - a headless CI box should still be able to run the logic tests.
    """
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display available for Tk tests")
    root.withdraw()
    yield root
    # Deliberately not destroyed: leaving it alive keeps the font database
    # valid for any test that runs afterwards.
