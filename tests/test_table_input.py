"""Tests for the playlist table's keyboard and selection behaviour.

Tk's Treeview gives arrow keys and Space and almost nothing else, so the rest
is hand-rolled here. Hand-rolled input handling is easy to get subtly wrong,
so these drive the real widgets and the real key sequences rather than calling
helpers directly.
"""

import tkinter as tk

import pytest

from musicdl.ui.widgets import PlaylistTable


@pytest.fixture
def table(tk_root):
    """A table populated with six rows, wired to a throwaway sink."""
    seen = []
    t = PlaylistTable(tk_root, seen.append, dark=True)
    # The table has to be mapped into the window: Tk refuses to set keyboard
    # focus on an unmapped widget, which would make every focus assertion here
    # vacuously pass.
    t.pack(fill="both", expand=True)
    entries = [
        {"id": f"v{i}", "title": f"Song {i}", "uploader": f"Artist {i % 2}"}
        for i in range(6)
    ]
    t.populate(entries)
    tk_root.update()
    # Focus starts on the list, as it does in the app. Tk routes a key event
    # to the focus widget, so a shortcut bound on the tree only fires when the
    # tree actually holds focus - without this the key goes nowhere and the
    # shortcut tests would pass or fail for the wrong reason.
    t.tree.focus_set()
    tk_root.update()
    yield t
    t._loader.shutdown()
    t.destroy()


def press(widget, sequence):
    """Deliver a real key sequence to a widget and process it."""
    widget.event_generate(sequence, when="now")
    widget.update()


def selected_text(entry):
    """The text currently selected inside an entry, by its own indexes.

    Deliberately avoids ``entry.selection_get()``, which with no argument
    reads the X11 PRIMARY selection - the last text selected anywhere in the
    session - rather than the entry's own selection.
    """
    if not entry.selection_present():
        return ""
    # Entry.get() takes no start/end arguments, so slice the full value with
    # the indexes the entry reports for its own selection.
    return entry.get()[entry.index("sel.first"):entry.index("sel.last")]


def has_focus(root, widget):
    """True when ``widget`` is the focus target within ``root``.

    ``focus_get()`` is the answer, but it must be read the way Tk means it.
    On any widget in a toplevel it returns *that toplevel's* focused widget -
    even when the widget asked cannot hold focus itself. So a naive "walk the
    children and return the first non-None" search reports whichever child it
    happened to visit first, which is arbitrary. Comparing the reported path
    against the widget's own path sidesteps the walk entirely: one query,
    no traversal, and no dependence on child order.
    """
    try:
        focused = root.focus_get()
    except tk.TclError:
        return False
    if focused is None:
        return False
    return str(focused) == str(widget)


class TestFilterShortcuts:
    def test_ctrl_f_focuses_the_filter(self, table, tk_root):
        # Ctrl+F is bound on the tree, so the key has to be delivered there -
        # which is also where focus rests during ordinary use.
        press(table.tree, "<Control-f>")
        assert has_focus(tk_root, table.filter_entry)

    def test_ctrl_f_selects_existing_text(self, table, tk_root):
        table.filter_var.set("Song")
        press(table.tree, "<Control-f>")
        # Read the entry's own selection, not `selection_get()`: with no
        # argument that reads the X11 PRIMARY selection, which is whatever
        # text happened to be last selected elsewhere in the session - not
        # what this entry has selected.
        assert selected_text(table.filter_entry) == "Song"

    def test_escape_clears_the_filter(self, table, tk_root):
        table.filter_var.set("Song 3")
        table.filter_entry.focus_set()
        press(table.filter_entry, "<Escape>")
        assert table.filter_var.get() == ""
        assert len(table.tree.get_children("")) == 6

    def test_escape_when_already_empty_returns_focus_to_the_list(
            self, table, tk_root):
        """A second Escape should move on, not require a third press."""
        table.filter_entry.focus_set()
        press(table.filter_entry, "<Escape>")
        assert has_focus(tk_root, table.tree)

    def test_filtering_narrows_and_escape_restores(self, table):
        table.filter_var.set("Song 3")
        table.update_idletasks()
        assert len(table.tree.get_children("")) == 1
        table.filter_var.set("")
        table.update_idletasks()
        assert len(table.tree.get_children("")) == 6

    def test_clear_filter_is_a_noop_when_empty(self, table):
        assert table.clear_filter() == "break"
        assert table.filter_var.get() == ""


class TestSelectionShortcuts:
    def test_space_toggles_the_selection(self, table):
        table.tree.focus_set()
        iids = table.visible_order()
        table.tree.selection_set(iids[:2])
        table.toggle_checked(table.vid_by_iid[iids[0]])
        press(table.tree, "<space>")
        assert not table.checked[table.vid_by_iid[iids[1]]]

    def test_ctrl_a_ticks_everything(self, table):
        table.set_all_checked(False)
        table.tree.focus_set()
        press(table.tree, "<Control-a>")
        assert len(table.checked_ids()) == 6

    def test_shift_space_sets_a_known_state(self, table):
        """Flipping a mixed selection is unpredictable; this sets it instead."""
        table.set_all_checked(False)
        table.tree.focus_set()
        table.tree.selection_set(table.visible_order()[:3])
        press(table.tree, "<Shift-space>")
        assert all(table.checked[table.vid_by_iid[i]]
                   for i in table.tree.selection())

    def test_shift_space_unticks_a_fully_ticked_selection(self, table):
        table.set_all_checked(True)
        table.tree.focus_set()
        table.tree.selection_set(table.visible_order()[:2])
        press(table.tree, "<Shift-space>")
        assert not any(table.checked[table.vid_by_iid[i]]
                       for i in table.tree.selection())

    def test_shift_space_with_nothing_selected_does_nothing(self, table):
        table.tree.focus_set()
        table.tree.selection_remove(table.visible_order())
        before = dict(table.checked)
        press(table.tree, "<Shift-space>")
        assert table.checked == before


class TestShiftExtendSelection:
    def test_extends_downward_from_the_anchor(self, table):
        order = table.visible_order()
        table._anchor = order[1]
        table._extend_selection_to(order[4])
        assert len(table.tree.selection()) == 4

    def test_extends_upward_from_the_anchor(self, table):
        order = table.visible_order()
        table._anchor = order[4]
        table._extend_selection_to(order[1])
        assert len(table.tree.selection()) == 4

    def test_anchor_is_the_start_of_the_range(self, table):
        """Re-extending must not creep the range start along with the end."""
        order = table.visible_order()
        table._anchor = order[0]
        table._extend_selection_to(order[2])
        table._extend_selection_to(order[5])
        assert len(table.tree.selection()) == 6

    def test_a_filtered_out_anchor_starts_a_fresh_range(self, table):
        """Regression: an invisible anchor must not raise or select nothing."""
        order = table.visible_order()
        table._anchor = order[0]
        table.filter_var.set("Song 4")
        table.update_idletasks()
        visible = table.visible_order()
        table._extend_selection_to(visible[-1])
        assert len(table.tree.selection()) >= 1
        assert table._anchor == visible[-1]

    def test_single_row_range(self, table):
        order = table.visible_order()
        table._anchor = order[2]
        table._extend_selection_to(order[2])
        assert len(table.tree.selection()) == 1


class TestFocusability:
    def test_tree_is_a_tab_stop(self, table, tk_root):
        """Without takefocus the list is unreachable by keyboard."""
        assert str(table.tree.cget("takefocus")) in ("1", "True", "true")

    def test_tree_accepts_focus(self, table, tk_root):
        table.tree.focus_set()
        table.update()
        assert has_focus(tk_root, table.tree)
