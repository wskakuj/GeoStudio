"""Undo/redo engine for map edits and their visual sidecars.

One history entry is one user action, applied atomically across three stores:
the raw ``bytes`` lines of the map, ``visual_styles`` and ``label_positions``.

Design notes that matter:

* Patches store the original ``bytes`` taken straight from ``lines``. Nothing is
  decoded, re-encoded, stripped or normalised, so CP1250 text, CRLF line
  endings and unknown GEO-MAP records come back exactly as they were.
* A single prefix/suffix diff would swallow everything between two distant
  changes, so changes are split into hunks with SequenceMatcher.
* Every undo/redo verifies the state it expects to find before touching
  anything, and restores the previous good state if applying fails.
* ``is_dirty`` compares state identifiers, not a counter: undoing and then
  making a new edit produces a different branch, and must not look "saved".

The module is free of Qt and of the application window; it only needs a target
object exposing ``lines``, ``visual_styles``, ``label_positions`` and
``reparse()``.
"""
from __future__ import annotations

import copy
import difflib
from dataclasses import dataclass, field
from typing import Any, Iterable, Protocol

ROOT_STATE = 0
DEFAULT_LIMIT = 200
DEFAULT_BYTE_BUDGET = 32 * 1024 * 1024
# Regions above this many changed lines are compared in blocks of BLOCK_LINES
# first, so distant edits stay in separate hunks.
REFINE_LINES = 2048
BLOCK_LINES = 64


class HistoryConflict(RuntimeError):
    """The document is not in the state the entry expects; nothing was applied."""


class HistoryTarget(Protocol):
    """What the engine needs from a document."""

    lines: list[bytes]
    visual_styles: dict[str, dict]
    label_positions: dict[str, dict]

    def reparse(self) -> None: ...


@dataclass(frozen=True)
class Hunk:
    """One contiguous replacement in the line list."""

    start: int
    removed: tuple[bytes, ...]
    added: tuple[bytes, ...]

    @property
    def size(self) -> int:
        return sum(len(line) for line in self.removed) + \
            sum(len(line) for line in self.added)


@dataclass(frozen=True)
class StylesPatch:
    """Sidecar changes, one entry per affected object and field.

    ``None`` means "this key was absent". Values are deep copies, so nothing
    is shared with the live dictionaries.
    """

    visual_before: dict[str, dict | None] = field(default_factory=dict)
    visual_after: dict[str, dict | None] = field(default_factory=dict)
    labels_before: dict[str, dict | None] = field(default_factory=dict)
    labels_after: dict[str, dict | None] = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        return not (self.visual_before or self.visual_after
                    or self.labels_before or self.labels_after)

    @property
    def size(self) -> int:
        total = 0
        for mapping in (self.visual_before, self.visual_after,
                        self.labels_before, self.labels_after):
            for value in mapping.values():
                total += len(repr(value))
        return total


@dataclass(frozen=True)
class HistoryEntry:
    state_id: int
    label: str
    hunks: tuple[Hunk, ...] = ()
    styles: StylesPatch | None = None
    selection_before: tuple[str, ...] = ()
    selection_after: tuple[str, ...] = ()

    @property
    def size(self) -> int:
        return sum(hunk.size for hunk in self.hunks) + \
            (self.styles.size if self.styles else 0)


def _diff_region(old: list[bytes], new: list[bytes], offset: int, *,
                 block: int = 64, refine: int = 2048) -> tuple[Hunk, ...]:
    """Hunks for a region that already differs at both ends.

    Small regions are matched line by line. Large ones are first compared as
    blocks of ``block`` lines, which keeps two changes at opposite ends of a
    big map apart instead of producing one enormous replacement; the few
    differing blocks are then refined line by line.
    """
    if not old and not new:
        return ()
    if len(old) + len(new) <= refine:
        matcher = difflib.SequenceMatcher(a=old, b=new, autojunk=False)
        return tuple(Hunk(offset + i1, tuple(old[i1:i2]), tuple(new[j1:j2]))
                     for tag, i1, i2, j1, j2 in matcher.get_opcodes()
                     if tag != "equal")

    old_blocks = [tuple(old[i:i + block]) for i in range(0, len(old), block)]
    new_blocks = [tuple(new[i:i + block]) for i in range(0, len(new), block)]
    matcher = difflib.SequenceMatcher(a=old_blocks, b=new_blocks, autojunk=False)
    hunks: list[Hunk] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        old_start, old_end = i1 * block, min(i2 * block, len(old))
        new_start, new_end = j1 * block, min(j2 * block, len(new))
        if (old_end - old_start) + (new_end - new_start) <= refine:
            hunks.extend(_diff_region(old[old_start:old_end],
                                      new[new_start:new_end],
                                      offset + old_start,
                                      block=block, refine=refine))
        else:
            hunks.append(Hunk(offset + old_start,
                              tuple(old[old_start:old_end]),
                              tuple(new[new_start:new_end])))
    return tuple(hunks)


def diff_lines(old: list[bytes], new: list[bytes], *,
               block: int = 64, refine: int = 2048) -> tuple[Hunk, ...]:
    """Minimal hunks turning ``old`` into ``new``.

    The common prefix and suffix are trimmed first, then the remaining region
    is diffed with block anchors so that distant changes stay separate and
    small. Two edits a hundred thousand lines apart produce two hunks of a few
    hundred bytes, not one of several megabytes.
    """
    if old == new:
        return ()
    limit = min(len(old), len(new))
    prefix = 0
    while prefix < limit and old[prefix] == new[prefix]:
        prefix += 1
    suffix = 0
    while (suffix < limit - prefix
           and old[len(old) - 1 - suffix] == new[len(new) - 1 - suffix]):
        suffix += 1
    return _diff_region(old[prefix:len(old) - suffix],
                        new[prefix:len(new) - suffix], prefix,
                        block=block, refine=refine)


def _style_delta(before: dict, after: dict) -> dict[str, dict | None]:
    """Deep-copied before/after values for the keys that actually changed."""
    delta: dict[str, dict | None] = {}
    for key in set(before) | set(after):
        old = before.get(key)
        new = after.get(key)
        if old != new:
            delta[key] = copy.deepcopy(old) if old is not None else None
    return delta


def build_styles_patch(before_visual: dict, after_visual: dict,
                       before_labels: dict, after_labels: dict) -> StylesPatch:
    return StylesPatch(
        visual_before=_style_delta(before_visual, after_visual),
        visual_after=_style_delta(after_visual, before_visual),
        labels_before=_style_delta(before_labels, after_labels),
        labels_after=_style_delta(after_labels, before_labels),
    )


class Transaction:
    """Context manager wrapping one user action.

    On success it records one entry. On an exception, or when the target cannot
    be re-parsed, the pre-action state is restored and nothing is recorded.
    """

    def __init__(self, history: "History", label: str,
                 selection_before: Iterable[str] = ()):
        self._history = history
        self._label = label
        self._selection_before = tuple(selection_before)
        self._selection_after: tuple[str, ...] | None = None
        self._lines: list[bytes] = []
        self._visual: dict = {}
        self._labels: dict = {}
        self.entry: HistoryEntry | None = None

    def set_selection_after(self, uids: Iterable[str]) -> None:
        self._selection_after = tuple(uids)

    def __enter__(self) -> "Transaction":
        target = self._history.target
        self._lines = list(target.lines)
        self._visual = copy.deepcopy(target.visual_styles)
        self._labels = copy.deepcopy(target.label_positions)
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        if exc_type is not None:
            self._rollback()
            return False
        hunks = diff_lines(self._lines, self._history.target.lines)
        styles = build_styles_patch(self._visual,
                                    self._history.target.visual_styles,
                                    self._labels,
                                    self._history.target.label_positions)
        if not hunks and styles.is_empty:
            return False
        self.entry = self._history._push(HistoryEntry(
            state_id=0,
            label=self._label,
            hunks=hunks,
            styles=None if styles.is_empty else styles,
            selection_before=self._selection_before,
            selection_after=(self._selection_after
                             if self._selection_after is not None
                             else self._selection_before),
        ))
        return False

    def _rollback(self) -> None:
        target = self._history.target
        target.lines[:] = self._lines
        target.visual_styles.clear()
        target.visual_styles.update(copy.deepcopy(self._visual))
        target.label_positions.clear()
        target.label_positions.update(copy.deepcopy(self._labels))
        target.reparse()


def set_values(store: dict, values: dict[str, dict | None]) -> None:
    """Write deep copies into a sidecar store; ``None`` removes the key."""
    for uid, value in values.items():
        if value is None:
            store.pop(uid, None)
        else:
            store[uid] = copy.deepcopy(value)


class History:
    """Bounded undo/redo stack over a :class:`HistoryTarget`."""

    def __init__(self, target: HistoryTarget, *, limit: int = DEFAULT_LIMIT,
                 byte_budget: int = DEFAULT_BYTE_BUDGET):
        self.target = target
        self.limit = max(1, int(limit))
        self.byte_budget = max(0, int(byte_budget))
        self._entries: list[HistoryEntry] = []
        self._index = 0
        self._next_state = ROOT_STATE + 1
        self._saved_state = ROOT_STATE

    # -- recording ------------------------------------------------------
    def begin(self, label: str, *,
              selection_before: Iterable[str] = ()) -> Transaction:
        return Transaction(self, label, selection_before)

    def _push(self, entry: HistoryEntry) -> HistoryEntry:
        entry = HistoryEntry(state_id=self._next_state, label=entry.label,
                             hunks=entry.hunks, styles=entry.styles,
                             selection_before=entry.selection_before,
                             selection_after=entry.selection_after)
        self._next_state += 1
        del self._entries[self._index:]
        self._entries.append(entry)
        self._index += 1
        self._trim()
        return entry

    def _trim(self) -> None:
        while len(self._entries) > self.limit:
            del self._entries[0]
            self._index = max(0, self._index - 1)
        while (self.byte_budget and self._entries
               and sum(entry.size for entry in self._entries) > self.byte_budget
               and len(self._entries) > 1):
            del self._entries[0]
            self._index = max(0, self._index - 1)

    # -- applying -------------------------------------------------------
    def undo(self) -> HistoryEntry | None:
        if not self.can_undo:
            return None
        entry = self._entries[self._index - 1]
        self._apply(entry, forward=False)
        self._index -= 1
        return entry

    def redo(self) -> HistoryEntry | None:
        if not self.can_redo:
            return None
        entry = self._entries[self._index]
        self._apply(entry, forward=True)
        self._index += 1
        return entry

    def _apply(self, entry: HistoryEntry, *, forward: bool) -> None:
        target = self.target
        saved_lines = list(target.lines)
        saved_visual = copy.deepcopy(target.visual_styles)
        saved_labels = copy.deepcopy(target.label_positions)

        try:
            self._verify(entry, forward=forward)
            for hunk in sorted(entry.hunks, key=lambda item: item.start,
                               reverse=True):
                # undo: the "added" text must be present, replace it with
                # what was there before. redo: the opposite.
                expected = hunk.removed if forward else hunk.added
                replacement = hunk.added if forward else hunk.removed
                start = hunk.start
                target.lines[start:start + len(expected)] = list(replacement)
            if entry.styles is not None:
                self._apply_styles(target.visual_styles, target.label_positions,
                                   entry.styles, forward=forward)
            target.reparse()
        except Exception:
            target.lines[:] = saved_lines
            target.visual_styles.clear()
            target.visual_styles.update(saved_visual)
            target.label_positions.clear()
            target.label_positions.update(saved_labels)
            target.reparse()
            raise

    def _verify(self, entry: HistoryEntry, *, forward: bool) -> None:
        target = self.target
        for hunk in entry.hunks:
            expected = hunk.removed if forward else hunk.added
            start = hunk.start
            current = target.lines[start:start + len(expected)]
            if list(current) != list(expected):
                raise HistoryConflict(
                    f"Historia nie zgadza się z dokumentem: rekordy od wiersza "
                    f"{start} zmieniono poza historią.")
        styles = entry.styles
        if styles is not None:
            self._verify_sidecar(target.visual_styles,
                                 styles.visual_before if forward else styles.visual_after,
                                 'stylów')
            self._verify_sidecar(target.label_positions,
                                 styles.labels_before if forward else styles.labels_after,
                                 'pozycji etykiet')

    @staticmethod
    def _verify_sidecar(current: dict, expected: dict[str, dict | None],
                        what: str) -> None:
        for uid, value in expected.items():
            if current.get(uid) != value:
                raise HistoryConflict(
                    f"Historia nie zgadza się z dokumentem: {what} obiektu "
                    f"{uid} zmieniono poza historią.")

    @staticmethod
    def _apply_styles(visual_store: dict, label_store: dict,
                      patch: StylesPatch, *, forward: bool) -> None:
        # undo restores the "before" side, redo re-applies the "after" side
        set_values(visual_store,
                   patch.visual_after if forward else patch.visual_before)
        set_values(label_store,
                   patch.labels_after if forward else patch.labels_before)

    # -- state ----------------------------------------------------------
    @property
    def can_undo(self) -> bool:
        return self._index > 0

    @property
    def can_redo(self) -> bool:
        return self._index < len(self._entries)

    @property
    def next_undo_label(self) -> str:
        return self._entries[self._index - 1].label if self.can_undo else ''

    @property
    def next_redo_label(self) -> str:
        return self._entries[self._index].label if self.can_redo else ''

    @property
    def undo_depth(self) -> int:
        return self._index

    @property
    def redo_depth(self) -> int:
        return len(self._entries) - self._index

    @property
    def current_state_id(self) -> int:
        return self._entries[self._index - 1].state_id if self._index else ROOT_STATE

    @property
    def saved_state_id(self) -> int:
        return self._saved_state

    @property
    def is_dirty(self) -> bool:
        return self.current_state_id != self._saved_state

    def mark_saved(self) -> None:
        """Record that the current state reached the disk — all of it.

        Callers must invoke this only after the map *and* the sidecar were
        written successfully; a half-finished save is not a save.
        """
        self._saved_state = self.current_state_id

    def clear(self) -> None:
        """Forget everything; used when another document is opened."""
        self._entries.clear()
        self._index = 0
        self._saved_state = ROOT_STATE
