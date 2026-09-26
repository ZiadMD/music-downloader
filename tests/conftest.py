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
    # The window has to be mapped, because Tk refuses to set keyboard focus on
    # an unmapped toplevel - which would make every focus assertion below pass
    # without testing anything.
    #
    # It is also made fully transparent rather than moved off-screen. Under
    # Wayland an off-screen window is outside the compositor's idea of the
    # visible area and never receives keyboard focus, so `focus_set()` appears
    # to do nothing and the focus assertions fail for a reason that has
    # nothing to do with the code under test. Alpha 0 keeps the window mapped
    # and focusable while making it invisible, which works on both X11 and
    # Wayland and still never flashes on a developer's desktop.
    root.attributes("-alpha", 0.0)
    root.update()
    yield root
    # Deliberately not destroyed: leaving it alive keeps the font database
    # valid for any test that runs afterwards.
