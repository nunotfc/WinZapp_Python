"""The composer cues a spelling error when the caret arrives at a misspelled
word (arrow keys, Ctrl+arrows, Home/End, a click) and only then: typing has
its own path (on_change_message_field). Unbound methods on plain stubs, no
window."""

from types import SimpleNamespace

import pytest
import wx

from core.spell_checker import WindowsSpellChecker
from ui.conversation_panel import composer
from ui.conversation_panel.composer import ComposerMixin


class _Field:
    def __init__(self, value="", position=0):
        self.value, self.position = value, position

    def GetValue(self):
        return self.value

    def GetInsertionPoint(self):
        return self.position


class _Panel:
    _check_spelling_at_caret = ComposerMixin._check_spelling_at_caret
    _on_message_field_key_down = ComposerMixin._on_message_field_key_down
    _on_message_field_mouse_up = ComposerMixin._on_message_field_mouse_up

    def __init__(self, text="good wrod fine", position=0, enabled=True):
        self.message_field = _Field(text, position)
        self._enabled = enabled
        self.played = []
        self._spell_checker = WindowsSpellChecker(on_error=lambda: self.played.append(True))
        self._spell_checker.errors_for_text = lambda value: [(5, 9)]
        self._mention_panel = SimpleNamespace(IsShown=lambda: False)
        self._mention_list = SimpleNamespace()

    def _spell_check_enabled(self):
        return self._enabled


def _key(code, **flags):
    event = SimpleNamespace(skipped=False)
    event.GetKeyCode = lambda: code
    event.ShiftDown = lambda: flags.get("shift", False)
    event.Skip = lambda: setattr(event, "skipped", True)
    return event


@pytest.fixture
def deferred(monkeypatch):
    queued = []
    monkeypatch.setattr(composer.wx, "CallAfter", lambda fn, *a: queued.append((fn, a)))
    return queued


@pytest.mark.parametrize("code", [wx.WXK_LEFT, wx.WXK_RIGHT, wx.WXK_UP, wx.WXK_DOWN,
                                  wx.WXK_HOME, wx.WXK_END, wx.WXK_PAGEUP, wx.WXK_PAGEDOWN])
def test_a_caret_key_schedules_the_check_after_the_native_control_moved_and_is_not_consumed(deferred, code):
    panel = _Panel()
    event = _key(code)

    panel._on_message_field_key_down(event)

    assert event.skipped                       # the control still moves the caret
    assert [fn.__name__ for fn, _ in deferred] == ["_check_spelling_at_caret"]


@pytest.mark.parametrize("code", [ord("A"), wx.WXK_SPACE, wx.WXK_BACK, wx.WXK_DELETE, wx.WXK_TAB])
def test_typing_and_editing_keys_schedule_nothing(deferred, code):
    panel = _Panel()
    panel._on_message_field_key_down(_key(code))
    assert deferred == []


def test_shift_enter_still_inserts_a_newline_without_a_caret_check(deferred):
    panel = _Panel()
    inserted = []
    panel.message_field.WriteText = inserted.append
    panel.on_change_message_field = lambda event: None
    panel._on_message_field_key_down(_key(wx.WXK_RETURN, shift=True))
    assert inserted == ["\n"] and deferred == []


def test_a_click_schedules_the_check_too(deferred):
    panel = _Panel()
    event = SimpleNamespace(Skip=lambda: setattr(event, "skipped", True))
    panel._on_message_field_mouse_up(event)
    assert event.skipped and [fn.__name__ for fn, _ in deferred] == ["_check_spelling_at_caret"]


def test_the_check_cues_when_the_caret_is_on_the_misspelled_word():
    panel = _Panel(position=6)
    panel._check_spelling_at_caret()
    assert panel.played == [True]


def test_the_check_is_silent_elsewhere_and_cues_once_per_arrival():
    panel = _Panel(position=1)
    panel._check_spelling_at_caret()
    assert panel.played == []
    for position in (5, 6, 7):
        panel.message_field.position = position
        panel._check_spelling_at_caret()
    assert panel.played == [True]


def test_nothing_happens_while_spell_checking_is_off():
    panel = _Panel(position=6, enabled=False)
    panel._check_spelling_at_caret()
    assert panel.played == []


def test_nothing_happens_without_a_checker():
    panel = _Panel(position=6)
    panel._spell_checker = None
    panel._check_spelling_at_caret()
    assert panel.played == []


def test_a_destroyed_field_is_ignored():
    panel = _Panel(position=6)

    def gone():
        raise RuntimeError("wrapped C/C++ object of type TextCtrl has been deleted")
    panel.message_field.GetValue = gone
    panel._check_spelling_at_caret()
    assert panel.played == []


def test_the_caret_position_is_converted_for_windows_line_breaks(monkeypatch):
    monkeypatch.setattr(composer.sys, "platform", "win32")
    # "wrod" starts on the second line: native position counts the break as two.
    panel = _Panel(text="ok\nwrod", position=4)     # native 4 = after CR LF and 'w'
    panel._spell_checker.errors_for_text = lambda value: [(3, 7)]
    panel._check_spelling_at_caret()
    assert panel.played == [True]
    monkeypatch.setattr(composer.sys, "platform", "linux")
    other = _Panel(text="ok\nwrod", position=2)     # one-position breaks: 2 is before the break
    other._spell_checker.errors_for_text = lambda value: [(3, 7)]
    other._check_spelling_at_caret()
    assert other.played == []


def test_the_message_field_is_bound_to_the_click_handler():
    source = open("client/ui/conversations.py", encoding="utf-8").read()
    assert "wx.EVT_LEFT_UP,    self._on_message_field_mouse_up" in source
