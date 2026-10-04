"""Pure-logic tests for the small message-field spell-check adapter."""

import core.spell_checker as spell_checker
from core.spell_checker import WindowsSpellChecker, _word_ended
from tests.locales import registered_locale_codes


def test_word_ended_only_on_transition_to_whitespace():
    assert _word_ended("ktury", "ktury ")
    assert not _word_ended("ktury ", "ktury  ")
    assert not _word_ended("ktury", "ktur")
    assert not _word_ended("ktury drugi", "ktury ")
    assert not _word_ended("ktury", "ktury  ")


def test_checker_tracks_text_and_returns_errors_after_word_boundary():
    played = []
    checker = WindowsSpellChecker(on_error=lambda: played.append(True))
    checker.errors_for_text = lambda text: [(0, 5)] if text.startswith("ktury") else []
    assert checker.text_changed("ktury") == []
    assert checker.text_changed("ktury ") == [(0, 5)]
    assert played == [True]
    # A second space must not retrigger the same word.
    assert checker.text_changed("ktury  ") == []
    assert played == [True]


def test_deleting_a_misspelled_word_does_not_replay_the_sound():
    played = []
    checker = WindowsSpellChecker(on_error=lambda: played.append(True))
    checker.errors_for_text = lambda text: [(0, 5), (6, 11)]

    checker.text_changed("ktury drugi")
    assert checker.text_changed("ktury ") == []
    assert played == []


def test_language_candidates_prefer_winzapp_then_use_windows(monkeypatch):
    monkeypatch.setattr(
        spell_checker,
        "_windows_language_names",
        lambda: ["de-DE", "pl-PL"],
    )

    assert spell_checker._language_candidates("pl") == ["pl-PL", "de-DE"]


def test_changing_language_reopens_the_checker_lazily():
    checker = WindowsSpellChecker(language="pl")
    checker._initialized = True
    checker._checker = object()
    checker.language = "pl-PL"

    checker.set_language("en-US")

    assert checker.preferred_language == "en-US"
    assert checker.language == ""
    assert checker._checker is None
    assert checker._initialized is False


def test_reset_rebaselines_without_checking_or_cueing():
    """While the Settings > Geral switch is off the composer calls reset()
    instead of text_changed(), so re-enabling mid-message cannot mistake the
    text already in the field for a word just typed."""
    played = []
    checker = WindowsSpellChecker(on_error=lambda: played.append(True))
    checker.errors_for_text = lambda text: [(0, 5)]

    checker.reset("ktury")
    assert played == []

    # The very next keystroke is now a normal one-character append again.
    assert checker.text_changed("ktury ") == [(0, 5)]
    assert played == [True]


def test_reset_with_no_argument_clears_the_baseline():
    checker = WindowsSpellChecker()
    checker.text_changed("abc")
    checker.reset()
    assert checker._last_text == ""


def test_every_registered_locale_reaches_windows_with_a_region():
    # The Windows spelling API is given full BCP 47 tags (pl-PL, not the
    # "pl" language_map.json uses), so a bare code risks matching no
    # installed dictionary. A new region-less locale has to be mapped in
    # _WINZAPP_LANGUAGE_TAGS.
    for code in registered_locale_codes():
        tag = spell_checker._normalize_language_tag(code)
        assert "-" in tag, (code, tag)


# ── punctuation ends a word too ─────────────────────────────────────────

import pytest

from core.spell_checker import caret_index, is_word_boundary


@pytest.mark.parametrize("char", [" ", "\t", "\n", ",", ".", ";", ":", "!", "?", ")", "]", "}", '"', "…", "¿", "«", "—"])
def test_whitespace_and_punctuation_end_a_word(char):
    assert is_word_boundary(char)


@pytest.mark.parametrize("char", ["a", "Z", "ç", "ł", "7", "'", "’", "-", "‑", "_", "", "+", "$"])
def test_letters_digits_and_in_word_marks_do_not(char):
    assert not is_word_boundary(char)


def test_word_ended_on_punctuation_appended_right_after_a_word():
    assert _word_ended("ktury", "ktury,")
    assert _word_ended("ktury", "ktury.")
    assert _word_ended("ktury", "ktury?")
    assert _word_ended("ktury drugi", "ktury drugi;")


def test_word_ended_ignores_everything_that_is_not_a_fresh_boundary_after_a_word():
    assert not _word_ended("ktury,", "ktury,,")      # a second mark ends no word
    assert not _word_ended("ktury,", "ktury, ")      # nor a space after a mark
    assert not _word_ended("ktury ", "ktury .")      # nor a mark after a space
    assert not _word_ended("ktury", "ktury'")        # apostrophe lives inside words
    assert not _word_ended("ktury", "ktury-")        # so does a hyphen
    assert not _word_ended("ktury", "ktur,y")        # not an append
    assert not _word_ended("ktury,", "ktury")        # deleting is not typing


@pytest.mark.parametrize("boundary", [",", ".", ";", ":", "!", "?", ")"])
def test_a_misspelled_word_followed_by_punctuation_cues_the_error_like_a_space(boundary):
    played = []
    checker = WindowsSpellChecker(on_error=lambda: played.append(True))
    checker.errors_for_text = lambda text: [(0, 5)]
    checker.text_changed("ktury")

    assert checker.text_changed("ktury" + boundary) == [(0, 5)]
    assert played == [True]


def test_correct_word_followed_by_punctuation_is_silent():
    played = []
    checker = WindowsSpellChecker(on_error=lambda: played.append(True))
    checker.errors_for_text = lambda text: []
    checker.text_changed("hello")
    checker.text_changed("hello,")
    assert played == []


def test_apostrophe_or_hyphen_inside_a_word_is_not_checked_yet():
    calls = []
    checker = WindowsSpellChecker(on_error=lambda: None)
    checker.errors_for_text = lambda text: calls.append(text) or []
    checker.text_changed("d")
    checker.text_changed("d'")
    checker.text_changed("guarda-")
    assert calls == []


def test_deleting_back_over_punctuation_does_not_replay_the_sound():
    played = []
    checker = WindowsSpellChecker(on_error=lambda: played.append(True))
    checker.errors_for_text = lambda text: [(0, 5)]
    checker.text_changed("ktury,")
    checker.text_changed("ktury")
    assert played == []


# ── the caret arriving at a misspelled word ─────────────────────────────

TEXT = "good wrod fine"      # "wrod" is the error, characters 5..9
ERRORS = [(5, 9)]


def _checker(errors=ERRORS):
    played = []
    checker = WindowsSpellChecker(on_error=lambda: played.append(True))
    checker.errors_for_text = lambda text: list(errors)
    return checker, played


@pytest.mark.parametrize("index", [5, 6, 7, 8, 9])
def test_the_caret_on_a_misspelled_word_cues_it_at_every_position_of_the_word(index):
    checker, played = _checker()
    assert checker.caret_moved(TEXT, index) is True
    assert played == [True]


@pytest.mark.parametrize("index", [0, 4, 10, 14])
def test_the_caret_outside_a_misspelled_word_is_silent(index):
    checker, played = _checker()
    assert checker.caret_moved(TEXT, index) is False
    assert played == []


def test_walking_along_the_word_cues_once_and_coming_back_cues_again():
    checker, played = _checker()
    for index in (4, 5, 6, 7, 8, 9):     # arrow right through the word
        checker.caret_moved(TEXT, index)
    assert played == [True]
    for index in (10, 11):               # leave it
        checker.caret_moved(TEXT, index)
    assert played == [True]
    checker.caret_moved(TEXT, 9)         # arrow left back onto its end
    assert played == [True, True]


def test_ctrl_arrows_that_jump_from_word_to_word_cue_each_misspelled_one():
    errors = [(0, 3), (9, 12)]
    text = "abc good xyz"
    checker, played = _checker(errors)
    for index in (0, 5, 9, 12):          # Ctrl+Right: starts of each word, then the end
        checker.caret_moved(text, index)
    assert len(played) == 2              # abc, then xyz (once, though the end is inside too)


def test_two_adjacent_errors_each_cue_when_entered():
    errors = [(0, 3), (4, 7)]
    checker, played = _checker(errors)
    checker.caret_moved("abc def", 2)
    checker.caret_moved("abc def", 5)
    assert len(played) == 2


def test_typing_forgets_where_the_caret_was_so_the_same_word_cues_again():
    checker, played = _checker()
    checker.caret_moved(TEXT, 6)
    checker.text_changed("good wrod fine!")    # any edit invalidates the old ranges
    checker.caret_moved("good wrod fine!", 6)
    assert len(played) == 2


def test_reset_forgets_the_caret_word_too():
    checker, played = _checker()
    checker.caret_moved(TEXT, 6)
    checker.reset(TEXT)
    checker.caret_moved(TEXT, 6)
    assert len(played) == 2


def test_no_errors_means_no_cue_and_no_state_change():
    checker, played = _checker(errors=[])
    assert checker.caret_moved(TEXT, 6) is False
    assert played == [] and checker._caret_error is None


def test_a_broken_sound_never_breaks_caret_movement():
    checker = WindowsSpellChecker(on_error=lambda: 1 / 0)
    checker.errors_for_text = lambda text: list(ERRORS)
    assert checker.caret_moved(TEXT, 6) is True   # the failure is swallowed by the cue


@pytest.mark.parametrize("text,native,width,expected", [
    ("abc", 0, 1, 0), ("abc", 2, 1, 2), ("abc", 3, 1, 3), ("abc", 99, 1, 3), ("", 5, 2, 0),
    ("ab\ncd", 2, 2, 2),   # before the break
    ("ab\ncd", 3, 2, 3),   # between CR and LF: snaps to after the break
    ("ab\ncd", 4, 2, 3),   # after the break
    ("ab\ncd", 5, 2, 4), ("ab\ncd", 3, 1, 3),
    ("ab\r\ncd", 4, 2, 4), ("ab\r\ncd", 5, 2, 5),   # a text already holding CR LF
    ("a\n\nb", 5, 2, 3),
])
def test_caret_index_accounts_for_the_two_position_line_break_of_windows(text, native, width, expected):
    assert caret_index(text, native, width) == expected
