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
    # The window is mapped rather than withdrawn, because Tk refuses to set
    # keyboard focus on an unmapped toplevel - which would make every focus
    # assertion below vacuously pass. It is moved off-screen instead of being
    # hidden, so nothing flashes on a developer's desktop.
    root.geometry("+2000+2000")
    root.update()
    yield root
    # Deliberately not destroyed: leaving it alive keeps the font database
    # valid for any test that runs afterwards.
