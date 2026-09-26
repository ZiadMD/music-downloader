"""Modal dialogs used by the app."""

import threading

import ttkbootstrap as tb

# How long a worker will block waiting for the user to answer a rename prompt.
RENAME_TIMEOUT_SECONDS = 3600


def ask_rename(root, entry, emit):
    """Show a Skip / Rename / Cancel dialog and return the choice.

    ``emit`` is called with ``(ASK_RENAME, entry)`` to hand the entry to the
    main thread (Tk widgets may only be touched there). The returned string is
    one of ``"skip"``, ``"rename"``, ``"cancel"``.
    """
    answer = {"value": "cancel"}
    win = tb.Toplevel(root)
    win.title("Name already exists")
    win.transient(root)
    win.resizable(False, False)

    frame = tb.Frame(win, padding=16)
    frame.pack(fill="both", expand=True)
    tb.Label(
        frame,
        text=(f"A saved file already has the same name as:\n\n"
              f"  {entry['title']}\n\n"
              "What should I do with this download?"),
        justify="left", wraplength=420,
    ).pack(anchor="w")

    buttons = tb.Frame(frame)
    buttons.pack(fill="x", pady=(16, 0))

    def decide(value):
        answer["value"] = value
        win.destroy()

    for text, value, style in (
        ("Skip this song", "skip", "secondary"),
        ("Rename to 'Title (2)'", "rename", "info"),
        ("Cancel rest", "cancel", "danger"),
    ):
        tb.Button(buttons, text=text, bootstyle=style, width=18,
                  command=lambda v=value: decide(v)).pack(side="left", padx=4)

    win.grab_set()
    win.wait_window()
    return answer["value"]


class RenamePrompter:
    """Runs :func:`ask_rename` on the Tk thread and blocks the worker on it.

    A download thread that finds a name collision needs a user decision, but
    Tk is not thread-safe. The worker calls :meth:`ask`, which hands the entry
    to the main thread and waits on an :class:`threading.Event`; the UI's queue
    pump calls :meth:`show` to raise the dialog and release it.
    """

    def __init__(self, emit):
        self._emit = emit
        self._events = {}
        self._answers = {}

    def ask(self, entry) -> str:
        """Block the calling worker until the user answers. Never raises."""
        vid = entry["id"]
        event = threading.Event()
        self._events[vid] = event
        self._answers[vid] = None
        self._emit(("ask_rename", entry))
        event.wait(RENAME_TIMEOUT_SECONDS)
        self._events.pop(vid, None)
        return self._answers.pop(vid, None) or "cancel"

    def show(self, root, entry) -> None:
        """Raise the dialog for a pending prompt. Called on the main thread."""
        vid = entry["id"]
        if vid not in self._events:
            return
        try:
            self._answers[vid] = ask_rename(root, entry, self._emit)
        finally:
            event = self._events.get(vid)
            if event:
                event.set()
