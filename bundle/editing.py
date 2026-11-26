"""In-memory changes and exact excerpts of immutable reader cards."""
from dataclasses import dataclass


@dataclass(frozen=True)
class SourceText:
    image: int
    field: str
    text: str
    scope: str | None = None


class EditSession:
    def __init__(self, cards):
        self.originals = tuple(cards)
        self._changes = {}

    @property
    def dirty(self):
        return bool(self._changes)

    def original(self, index, field):
        if not 0 <= index < len(self.originals):
            raise IndexError(index)
        return dict(self.originals[index].fields())[field]

    def value(self, index, field):
        key = (index, field)
        if key in self._changes:
            return self._changes[key]
        return self.original(index, field)

    def fields(self, index):
        return [(field, self._changes.get((index, field), value))
                for field, value in self.originals[index].fields()]

    def set_value(self, index, field, text):
        if text == self.original(index, field):
            self.restore(index, field)
        else:
            self._changes[index, field] = text

    def restore(self, index, field):
        self._changes.pop((index, field), None)

    def capture(self, index, field, text, *, scope=None):
        self.original(index, field)
        return SourceText(index, field, text, scope)
