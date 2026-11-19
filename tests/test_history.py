"""Unit tests for the undo/redo engine. No Qt, no window, no files.

The target is a tiny stand-in for GeoMap plus the two sidecar dictionaries, so
these tests pin the contract from docs/HISTORY_CONTRACT.md: exact bytes,
atomic multi-store entries, verification before applying, rollback on failure
and a dirty flag based on state identity rather than a counter.
"""
from __future__ import annotations

import copy
import hashlib

import pytest

from geostudio.history import (ROOT_STATE, History, HistoryConflict, Hunk,
                               build_styles_patch, diff_lines, set_values)

HEADER = b';# Plik danych systemu GEO-MAP ver=[ 8.00]  N=[          5] CHK=[00000000000000000000000000000000]\r\n'
EXT = b';# EXT 1000 0.000 0.000 100.000 100.000 #ST=0 CS=9 CM=21\r\n'
PARCEL = (b'*5216 8553090  15          0 \r\n'
          b':ID[P1]\r\n:A2[12/3]\r\n'
          b'P 1   0.000   0.000\r\nP 1   1.000   0.000\r\nP 1   0.000   0.000\r\n')

# Line indices in base_lines(): 0 header, 1 EXT, 2 object, 3 :ID, 4 :A2, 5-7 P.
ID_LINE = 3
A2_LINE = 4
FIRST_POINT = 5


def base_lines() -> list[bytes]:
    return [HEADER, EXT] + PARCEL.splitlines(keepends=True)


class FakeDoc:
    """Minimal HistoryTarget: byte lines plus the two sidecar dictionaries."""

    def __init__(self, lines=None, visual=None, labels=None):
        self.lines = list(base_lines() if lines is None else lines)
        self.visual_styles = copy.deepcopy(visual or {})
        self.label_positions = copy.deepcopy(labels or {})
        self.reparse_calls = 0
        self.fail_reparse = False

    def reparse(self):
        self.reparse_calls += 1
        if self.fail_reparse:
            raise ValueError('parse failed')

    # helpers used by tests to simulate an edit
    def replace_line(self, index, value: bytes):
        self.lines[index] = value

    def digest(self) -> str:
        return hashlib.sha256(b''.join(self.lines)).hexdigest()


@pytest.fixture
def doc():
    return FakeDoc(visual={'P1': {'fill': '#AABBCC', 'opacity': 40}},
                   labels={'P1': {'A2': [5.0, 6.0]}})


@pytest.fixture
def history(doc):
    return History(doc)


# --- patches -------------------------------------------------------------

def test_diff_returns_nothing_for_identical_lines():
    lines = base_lines()
    assert diff_lines(lines, list(lines)) == ()


def test_diff_is_minimal_for_one_changed_line():
    old = base_lines()
    new = list(old)
    new[A2_LINE] = b':A2[12/4]\r\n'
    hunks = diff_lines(old, new)
    assert len(hunks) == 1
    assert hunks[0].start == A2_LINE
    assert hunks[0].removed == (b':A2[12/3]\r\n',)
    assert hunks[0].added == (b':A2[12/4]\r\n',)


def test_distant_changes_produce_separate_small_hunks():
    """First and last vertex of a ring: one prefix/suffix diff would swallow
    everything between them, hunks must not."""
    old = base_lines() + [f'P 1   {i}.000   {i}.000\r\n'.encode() for i in range(50)]
    new = list(old)
    new[FIRST_POINT] = b'P 1   0.500   0.000\r\n'
    new[-1] = b'P 1   49.500   49.000\r\n'
    hunks = diff_lines(old, new)
    assert len(hunks) == 2
    assert sum(hunk.size for hunk in hunks) < 200
    assert hunks[0].start < hunks[1].start


def test_large_contiguous_change_stays_one_hunk():
    old = [f'P 1   {i}.000   0.000\r\n'.encode() for i in range(200)]
    new = old[:10] + [b'inne\r\n'] * 180 + old[190:]
    hunks = diff_lines(old, new, block=8, refine=8)
    assert len(hunks) == 1
    assert hunks[0].start == 10


def test_distant_changes_in_a_huge_map_stay_small():
    """Two edits far apart must not become one multi-megabyte patch."""
    lines = [f'P 1   {i}.000   {i}.000\r\n'.encode() for i in range(50000)]
    edited = list(lines)
    edited[10] = b'P 1   1.000   1.000\r\n'
    edited[-10] = b'P 1   9.000   9.000\r\n'
    hunks = diff_lines(lines, edited)
    assert len(hunks) == 2
    assert sum(hunk.size for hunk in hunks) < 500


# --- recording -----------------------------------------------------------

def test_transaction_records_one_entry(history, doc):
    with history.begin('Zmiana A2'):
        doc.replace_line(A2_LINE, b':A2[12/4]\r\n')
    assert history.undo_depth == 1
    assert history.next_undo_label == 'Zmiana A2'
    assert history.is_dirty


def test_no_entry_for_an_operation_without_changes(history, doc):
    with history.begin('Nic'):
        pass
    assert history.undo_depth == 0
    assert history.can_undo is False


def test_one_transaction_covers_many_edits(history, doc):
    with history.begin('Przesunięcie wierzchołka'):
        doc.replace_line(FIRST_POINT, b'P 1   0.100   0.000\r\n')
        doc.replace_line(FIRST_POINT + 1, b'P 1   1.100   0.000\r\n')
        doc.replace_line(FIRST_POINT + 2, b'P 1   0.100   0.000\r\n')
    assert history.undo_depth == 1


# --- undo and redo -------------------------------------------------------

def test_undo_restores_the_original_bytes(history, doc):
    original = doc.digest()
    with history.begin('Zmiana A2'):
        doc.replace_line(A2_LINE, b':A2[12/4]\r\n')
    history.undo()
    assert doc.digest() == original
    assert doc.lines[A2_LINE] == b':A2[12/3]\r\n'


def test_redo_restores_the_edited_bytes(history, doc):
    with history.begin('Zmiana A2'):
        doc.replace_line(A2_LINE, b':A2[12/4]\r\n')
    edited = doc.digest()
    history.undo()
    history.redo()
    assert doc.digest() == edited


def test_new_edit_after_undo_clears_redo(history, doc):
    with history.begin('A'):
        doc.replace_line(A2_LINE, b':A2[1]\r\n')
    history.undo()
    assert history.can_redo
    with history.begin('B'):
        doc.replace_line(A2_LINE, b':A2[2]\r\n')
    assert history.can_redo is False
    assert history.undo_depth == 1


def test_full_undo_of_many_operations_returns_to_the_start(history, doc):
    original = doc.digest()
    for step in range(10):
        with history.begin(f'krok {step}'):
            doc.replace_line(A2_LINE, f':A2[{step}]\r\n'.encode())
    while history.can_undo:
        history.undo()
    assert doc.digest() == original


def test_encoding_line_endings_and_unknown_records_survive():
    """CP1250 text, LF-only endings, no trailing newline, unknown records."""
    lines = [HEADER,
             EXT,
             b'*5216 8553090  15          0 \n',
             b':ID[P1]\n:A2[\xb3\xb1ka]\n',
             b':ZZZ[zachowaj]\n',
             b'P 1   0.000   0.000\n']
    doc = FakeDoc(lines=lines)
    history = History(doc)
    original = doc.digest()
    with history.begin('edycja'):
        doc.replace_line(ID_LINE, b':ID[P1]\n:A2[nowa]\n')
    history.undo()
    assert doc.digest() == original
    assert doc.lines[ID_LINE] == b':ID[P1]\n:A2[\xb3\xb1ka]\n'
    assert b'\r\n' not in doc.lines[ID_LINE]


def test_many_distant_insertions_in_one_history_step_are_fully_reversible():
    original = [f"row-{i:03d}\n".encode() for i in range(40)]
    doc = FakeDoc(lines=original)
    history = History(doc)
    with history.begin("Wspólne wierzchołki"):
        doc.lines.insert(5, b"vertex-A\n")
        doc.lines.insert(29, b"vertex-B\n")
        doc.lines.insert(35, b"vertex-C\n")
    edited = list(doc.lines)
    assert len(history._entries[0].hunks) >= 2
    history.undo()
    assert doc.lines == original
    history.redo()
    assert doc.lines == edited


def test_many_distant_deletions_in_one_history_step_are_reversible():
    original = [f"row-{i:03d}\n".encode() for i in range(35)]
    doc = FakeDoc(lines=original)
    history = History(doc)
    with history.begin("Usuń dwa węzły"):
        del doc.lines[25]
        del doc.lines[5]
    edited = list(doc.lines)
    history.undo()
    assert doc.lines == original
    history.redo()
    assert doc.lines == edited


def test_mixed_insertion_and_replacement_one_transaction_is_reversible():
    original = [f"row-{i:03d}\n".encode() for i in range(40)]
    doc = FakeDoc(lines=original)
    history = History(doc)
    with history.begin("Wspólne węzły"):
        doc.lines[2] = b"changed\n"
        doc.lines.insert(11, b"new-P\n")
        doc.lines[32] = b"changed-later\n"
    edited = list(doc.lines)
    history.undo()
    assert doc.lines == original
    history.redo()
    assert doc.lines == edited


# --- sidecar -------------------------------------------------------------

def test_styles_are_restored_in_the_same_entry(history, doc):
    original_visual = copy.deepcopy(doc.visual_styles)
    original_labels = copy.deepcopy(doc.label_positions)
    with history.begin('Usunięcie obiektu'):
        del doc.lines[2:]
        doc.visual_styles.pop('P1')
        doc.label_positions.pop('P1')
    assert doc.visual_styles == {} and doc.label_positions == {}
    history.undo()
    assert doc.visual_styles == original_visual
    assert doc.label_positions == original_labels
    assert doc.digest() == hashlib.sha256(b''.join(base_lines())).hexdigest()


def test_style_values_are_not_shared_with_the_patch(history, doc):
    live = doc.visual_styles['P1']
    with history.begin('Wypełnienie'):
        doc.visual_styles['P1'] = {'fill': '#112233', 'opacity': 10}
    stored = history._entries[0].styles.visual_before['P1']
    assert stored is not live                        # patch owns its own copy
    assert stored == {'fill': '#AABBCC', 'opacity': 40}
    history.undo()
    assert doc.visual_styles['P1'] == {'fill': '#AABBCC', 'opacity': 40}
    assert doc.visual_styles['P1'] is not stored     # and undo writes a copy


def test_label_position_list_is_deep_copied(history, doc):
    with history.begin('Etykieta'):
        doc.label_positions['P1']['A2'][0] = 99.0
    stored = history._entries[0].styles.labels_before['P1']['A2']
    assert stored is not doc.label_positions['P1']['A2']
    history.undo()
    assert doc.label_positions['P1']['A2'] == [5.0, 6.0]


def test_styles_patch_marks_removed_keys_as_none():
    patch = build_styles_patch({'A': {'fill': '#000000', 'opacity': 1}}, {},
                               {'A': {'A2': [1.0, 2.0]}}, {})
    assert patch.visual_before == {'A': {'fill': '#000000', 'opacity': 1}}
    assert patch.visual_after == {'A': None}
    assert patch.is_empty is False


# --- verification and failure -------------------------------------------

def test_undo_refuses_when_lines_changed_outside_history(history, doc):
    with history.begin('A2'):
        doc.replace_line(A2_LINE, b':A2[12/4]\r\n')
    doc.replace_line(A2_LINE, b':A2[obcy]\r\n')            # outside the history
    before = list(doc.lines)
    with pytest.raises(HistoryConflict):
        history.undo()
    assert doc.lines == before
    assert history.can_undo                       # history untouched


def test_undo_refuses_when_sidecar_changed_outside_history(history, doc):
    with history.begin('Wypełnienie'):
        doc.visual_styles['P1'] = {'fill': '#112233', 'opacity': 10}
    doc.visual_styles['P1'] = {'fill': '#999999', 'opacity': 99}
    with pytest.raises(HistoryConflict):
        history.undo()
    assert doc.visual_styles['P1']['fill'] == '#999999'


def test_failed_operation_restores_the_previous_state(history, doc):
    original = doc.digest()
    original_visual = copy.deepcopy(doc.visual_styles)
    with pytest.raises(ValueError):
        with history.begin('Błąd'):
            doc.replace_line(A2_LINE, b':A2[12/4]\r\n')
            doc.visual_styles['P1'] = {'fill': '#000000', 'opacity': 1}
            raise ValueError('operacja nie udała się')
    assert doc.digest() == original
    assert doc.visual_styles == original_visual
    assert history.undo_depth == 0


def test_failed_reparse_during_undo_restores_the_previous_state(history, doc):
    with history.begin('A2'):
        doc.replace_line(A2_LINE, b':A2[12/4]\r\n')
    edited = doc.digest()
    doc.fail_reparse = True
    with pytest.raises(ValueError):
        history.undo()
    doc.fail_reparse = False
    assert doc.digest() == edited
    assert history.can_undo


# --- state tracking ------------------------------------------------------

def test_dirty_flag_follows_state_not_counter(history, doc):
    with history.begin('A'):
        doc.replace_line(A2_LINE, b':A2[1]\r\n')
    history.mark_saved()
    assert history.is_dirty is False
    history.undo()
    assert history.is_dirty is True
    history.redo()
    assert history.is_dirty is False
    history.undo()
    with history.begin('inna gałąź'):
        doc.replace_line(A2_LINE, b':A2[9]\r\n')
    # same depth as the saved state, different state: must stay dirty
    assert history.undo_depth == 1
    assert history.is_dirty is True


def test_saved_state_survives_more_edits(history, doc):
    with history.begin('A'):
        doc.replace_line(A2_LINE, b':A2[1]\r\n')
    history.mark_saved()
    with history.begin('B'):
        doc.replace_line(A2_LINE, b':A2[2]\r\n')
    assert history.is_dirty
    history.undo()
    assert history.is_dirty is False


def test_clear_forgets_everything(history, doc):
    with history.begin('A'):
        doc.replace_line(A2_LINE, b':A2[1]\r\n')
    history.clear()
    assert history.can_undo is False and history.can_redo is False
    assert history.is_dirty is False
    assert history.current_state_id == ROOT_STATE


def test_selection_is_recorded_with_the_entry(history, doc):
    with history.begin('A', selection_before=['P1']) as tx:
        doc.replace_line(A2_LINE, b':A2[1]\r\n')
        tx.set_selection_after(['P1', 'P2'])
    entry = history._entries[0]
    assert entry.selection_before == ('P1',)
    assert entry.selection_after == ('P1', 'P2')


# --- limits --------------------------------------------------------------

def test_entry_limit_drops_the_oldest(doc):
    history = History(doc, limit=3)
    for step in range(5):
        with history.begin(f'krok {step}'):
            doc.replace_line(A2_LINE, f':A2[{step}]\r\n'.encode())
    assert len(history._entries) == 3
    assert [entry.label for entry in history._entries] == ['krok 2', 'krok 3', 'krok 4']


def test_byte_budget_drops_the_oldest(doc):
    history = History(doc, byte_budget=120)
    for step in range(4):
        with history.begin(f'krok {step}'):
            doc.replace_line(A2_LINE, f':A2[{"x" * 40}{step}]\r\n'.encode())
    assert 1 <= len(history._entries) < 4
    assert history._entries[-1].label == 'krok 3'
