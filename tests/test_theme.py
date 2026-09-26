"""Tests for :mod:`musicdl.ui.theme`.

The behaviour worth protecting is the three-state policy. A two-state toggle
looks simpler but silently loses the ability to follow the OS again once an
explicit preference has been set, so the resolution table is asserted
directly.
"""

import pytest

from musicdl.ui import theme, tokens


class TestResolve:
    @pytest.mark.parametrize("choice", ["light", "dark"])
    def test_explicit_choices_pass_through(self, choice):
        assert theme.resolve(choice) == choice

    def test_system_follows_the_os(self, monkeypatch):
        monkeypatch.setattr(theme, "detect_os_theme", lambda: "dark")
        assert theme.resolve("system") == "dark"

    def test_system_can_resolve_to_light(self, monkeypatch):
        monkeypatch.setattr(theme, "detect_os_theme", lambda: "light")
        assert theme.resolve("system") == "light"

    @pytest.mark.parametrize("choice", [None, "", "neon", "DARK", 42])
    def test_bad_values_follow_the_os_rather_than_defaulting_blind(
            self, monkeypatch, choice):
        """An unrecognised value must not silently pin a mode the user did not pick."""
        monkeypatch.setattr(theme, "detect_os_theme", lambda: "dark")
        assert theme.resolve(choice) == "dark"

    def test_explicit_choice_beats_the_os(self, monkeypatch):
        """The whole point of an override: it wins regardless of the OS."""
        monkeypatch.setattr(theme, "detect_os_theme", lambda: "dark")
        assert theme.resolve("light") == "light"


class TestIsDark:
    def test_true_for_dark(self):
        assert theme.is_dark("dark") is True

    def test_false_for_light(self):
        assert theme.is_dark("light") is False

    def test_follows_os_for_system(self, monkeypatch):
        monkeypatch.setattr(theme, "detect_os_theme", lambda: "light")
        assert theme.is_dark("system") is False
        monkeypatch.setattr(theme, "detect_os_theme", lambda: "dark")
        assert theme.is_dark("system") is True


class TestTtkTheme:
    @pytest.mark.parametrize("dark", [True, False])
    def test_resolves_to_a_real_theme_name(self, dark):
        name = theme.ttk_theme(dark)
        assert isinstance(name, str) and name
        assert name.endswith("dark" if dark else "light")

    @pytest.mark.parametrize("name", ["dark", "light"])
    def test_not_a_legacy_name(self, name):
        """darkly/litera are pre-2.0 and slated for removal in ttkbootstrap 3."""
        assert theme.ttk_theme(name == "dark") not in ("darkly", "litera")

    def test_light_and_dark_differ(self):
        assert theme.ttk_theme(True) != theme.ttk_theme(False)

    def test_module_constants_match_the_token_table(self):
        assert theme.DARK == tokens.TTK_THEME["dark"]
        assert theme.LIGHT == tokens.TTK_THEME["light"]


class TestDetectOsTheme:
    def test_returns_a_known_value(self):
        assert theme.detect_os_theme() in ("light", "dark")

    def test_gsettings_branch(self, monkeypatch):
        monkeypatch.setattr(theme.os, "name", "posix")
        monkeypatch.setattr(theme.sys, "platform", "linux")
        monkeypatch.setattr(theme.shutil, "which", lambda _c: "/usr/bin/gsettings")
        monkeypatch.setattr(theme, "_run", lambda *a, **k: "'prefer-dark'")
        assert theme.detect_os_theme() == "dark"

    def test_gtk_theme_env_is_honoured(self, monkeypatch):
        monkeypatch.setattr(theme.os, "name", "posix")
        monkeypatch.setattr(theme.sys, "platform", "linux")
        monkeypatch.setenv("GTK_THEME", "Adwaita:dark")
        assert theme.detect_os_theme() == "dark"

    def test_probe_failure_falls_back_to_light(self, monkeypatch):
        """A missing settings daemon must not crash startup."""
        monkeypatch.setattr(theme.os, "name", "posix")
        monkeypatch.setattr(theme.sys, "platform", "linux")
        monkeypatch.delenv("GTK_THEME", raising=False)
        monkeypatch.setattr(theme.shutil, "which", lambda _c: None)
        assert theme.detect_os_theme() == "light"

    def test_run_never_raises(self):
        assert theme._run(["definitely-not-a-real-binary-xyz"]) == ""


class TestApply:
    def test_returns_a_style(self, root):
        style = theme.apply(root, dark=True)
        assert style is not None
        assert style.theme is not None
        assert style.theme.name == theme.ttk_theme(True)

    @pytest.mark.parametrize("dark", [True, False])
    def test_applies_the_matching_tree_colours(self, root, dark):
        theme.apply(root, dark=dark)
        style = theme.apply(root, dark=dark)
        # ttk resolves a colour spec, so assert the geometry token and that a
        # background was actually configured rather than comparing colour
        # strings the theme may map through its own palette.
        assert style.lookup("Playlist.Treeview", "rowheight") == tokens.ROW_HEIGHT
        assert style.lookup("Playlist.Treeview", "background")

    def test_text_widgets_are_retinted(self, root):
        import tkinter as tk

        text = tk.Text(root)
        root._musicdl_text_widgets = (text,)
        theme.apply(root, dark=True)
        palette = tokens.palette(True)
        assert text.cget("bg") == palette.surface_sunken
        assert text.cget("fg") == palette.on_surface_secondary
        text.destroy()

    def test_a_broken_text_widget_does_not_stop_the_theme(self, root):
        class Dead:
            def config(self, **_k):
                raise RuntimeError("destroyed")

        root._musicdl_text_widgets = (Dead(),)
        theme.apply(root, dark=False)  # must not raise

    def test_missing_text_registry_is_fine(self, root):
        if hasattr(root, "_musicdl_text_widgets"):
            del root._musicdl_text_widgets
        theme.apply(root, dark=True)  # must not raise


@pytest.fixture
def root(tk_root):
    """The session-wide Tk root. Tests must not destroy it."""
    return tk_root
