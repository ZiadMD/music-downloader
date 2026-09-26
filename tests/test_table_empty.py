"""Tests for the table's empty state and row banding.

Both are purely visual, which makes them easy to assert wrongly: a test that
only checks "a label exists" passes just as happily when the label says
something wrong or covers the rows. These check the copy and the stacking,
because those are the parts that actually break.
"""

import pytest

from musicdl.ui.widgets import PlaylistTable


@pytest.fixture
def bare_table(tk_root):
    """A table with nothing in it - the state the app starts in."""
    t = PlaylistTable(tk_root, lambda _m: None, dark=True)
    t.pack(fill="both", expand=True)
    tk_root.update()
    yield t
    t._loader.shutdown()
    t.destroy()


def rows(n):
    return [{"id": f"v{i}", "title": f"Song {i}", "uploader": f"Artist {i % 2}"}
            for i in range(n)]


def is_shown(widget):
    """True when the widget occupies space in its parent."""
    return bool(widget.grid_info())


class TestEmptyState:
    def test_shown_before_anything_is_loaded(self, bare_table):
        assert is_shown(bare_table.empty)

    def test_says_what_to_do_about_it(self, bare_table):
        """An empty panel has to name the next action, not just the absence."""
        hint = bare_table.empty_hint.cget("text")
        assert "playlist" in hint.lower()
        assert "load" in hint.lower()

    def test_hidden_once_rows_arrive(self, bare_table):
        bare_table.populate(rows(3))
        bare_table.update()
        assert not is_shown(bare_table.empty)

    def test_filter_matching_nothing_is_a_different_message(self, bare_table):
        """'No playlist' and 'no search matches' are different problems."""
        bare_table.populate(rows(3))
        bare_table.filter_var.set("nothing here matches this")
        bare_table.update()
        assert is_shown(bare_table.empty)
        assert bare_table.empty_title.cget("text") == bare_table.FILTER_TITLE

    def test_filter_clearing_restores_the_rows(self, bare_table):
        bare_table.populate(rows(3))
        bare_table.filter_var.set("nothing here matches this")
        bare_table.update()
        bare_table.filter_var.set("")
        bare_table.update()
        assert not is_shown(bare_table.empty)
        assert len(bare_table.tree.get_children("")) == 3

    def test_sits_above_the_tree(self, bare_table):
        """The panel has to be above the rows, not behind them.

        Both widgets share one grid cell, so stacking order is the only thing
        separating them. If the panel is buried, the empty list shows through
        and the user sees a blank table with a caption under it.
        """
        children = bare_table.empty.master.winfo_children()
        assert children.index(bare_table.empty) > children.index(bare_table.tree)


class TestBanding:
    def test_alternate_rows_are_banded(self, bare_table):
        bare_table.populate(rows(4))
        bare_table.update()
        tagged = [bare_table.tree.item(iid, "tags")
                  for iid in bare_table.tree.get_children("")]
        banded = ["band" in tags for tags in tagged]
        assert banded == [False, True, False, True]

    def test_a_status_tag_survives_alongside_the_band(self, bare_table):
        """Banding is a background, so it must not displace the status colour."""
        bare_table.populate(rows(2))
        bare_table.set_status("v1", "Failed")
        bare_table.update()
        tags = bare_table.tree.item(bare_table.iid_by_id["v1"], "tags")
        assert "missing" in tags
        assert "band" in tags

    def test_bands_follow_position_not_identity(self, bare_table):
        """Re-banding on filter is what stops the stripes looking arbitrary.

        Banding is positional, so rows must be re-tagged whenever the visible
        order changes. A band that stayed attached to a row would leave a gap
        in the stripe pattern after a search.
        """
        bare_table.populate(rows(4))
        # "Artist 0" matches songs 0 and 2, so two rows survive and the
        # stripe pattern has to be re-established from scratch.
        bare_table.filter_var.set("Artist 0")
        bare_table.update()
        tagged = [bare_table.tree.item(iid, "tags")
                  for iid in bare_table.tree.get_children("")]
        assert len(tagged) == 2
        assert ["band" in t for t in tagged] == [False, True]

    def test_bands_survive_a_theme_change(self, bare_table):
        """A theme switch retints tags; the band must still be applied."""
        bare_table.populate(rows(2))
        bare_table.apply_style_colors(dark=False)
        bare_table.update()
        tags = bare_table.tree.item(bare_table.iid_by_id["v1"], "tags")
        assert "band" in tags
