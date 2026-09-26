"""Shared pytest fixtures.

Two GUI toolkits are in play: ttkbootstrap on Tk, and PySide6 on Qt. Both
need a session-wide application object, and both have global state that is
expensive or impossible to recreate - so like every other GUI test suite,
everything shares one.

Headless behaviour
------------------
Neither toolkit gets a real display. The Tk tests need a *mapped* toplevel
(because Tk refuses to set focus on an unmapped one) but it is made fully
transparent, so nothing appears on a developer's desktop. The Qt tests use
the ``offscreen`` platform plugin, which renders to a memory buffer and never
touches an X server or a Wayland compositor at all.

``QT_QPA_PLATFORM`` is set here, in-process, rather than being passed on the
command line for the whole run. ``offscreen`` is a Qt-only setting, but
exporting it for the entire suite changes the environment the Tk tests see,
and a couple of focus-sensitive tests start failing for a reason that has
nothing to do with the code under them. Setting it here keeps it scoped to
the Qt fixtures that actually want it.
"""

import os

import pytest


@pytest.fixture(scope="session")
def tk_root():
    """The one and only Tk root for the test session.

    Skips the tests that need it when there is no display, rather than failing
    - a headless CI box should still be able to run the logic tests.
    """
    import tkinter as tk

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


@pytest.fixture(scope="session")
def qapp():
    """The one and only ``QApplication``, on Qt's offscreen platform.

    Session-scoped because a second ``QApplication`` cannot be created in the
    same process, and because both ``QFontDatabase`` and the application-wide
    stylesheet are global.

    ``offscreen`` is forced rather than merely defaulted: a developer running
    the suite on a desktop would otherwise get real windows opening and
    closing for the Qt tests. Forcing it makes the suite behave identically on
    every machine, which is the entire point of a test suite.
    """
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app
