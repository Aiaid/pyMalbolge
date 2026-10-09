"""Dependency-free, ordered Malbolge20 memory images and a .data codec.

The -1 word means an unset cell. Segment order is significant: the bootstrap
generator visits segments in declaration/layout order, including empty ones.
"""

from dataclasses import dataclass
from typing import Tuple


MAX_WORD = 3 ** 20 - 1
_HEADERS = {
    "direct": "DIRECT_UNIT_CODE",
    "routine": "ROUTINE_CODE",
    "indirect": "INDIRECT_UNIT_CODE",
}
_KINDS = {header: kind for kind, header in _HEADERS.items()}


class MemoryImageError(ValueError):
    """A memory image or its textual representation is malformed."""


def _integer(value, minimum, maximum, role):
    if type(value) is not int or not minimum <= value <= maximum:
        raise MemoryImageError("%s must be an integer in %d..%d" %
                               (role, minimum, maximum))


@dataclass(frozen=True)
class MemorySegment:
    kind: str
    index: int
    offset: int
    words: Tuple[int, ...]

    def __post_init__(self):
        if self.kind not in _HEADERS:
            raise MemoryImageError("unknown memory segment kind %r" % self.kind)
        _integer(self.index, 0, MAX_WORD, "segment index")
        _integer(self.offset, 0, MAX_WORD, "segment offset")
        if type(self.words) is not tuple:
            raise MemoryImageError("segment words must be a tuple")
        if self.offset + len(self.words) > MAX_WORD + 1:
            raise MemoryImageError("memory segment extends past the address space")
        for word in self.words:
            _integer(word, -1, MAX_WORD, "memory word")


@dataclass(frozen=True)
class MemoryImage:
    entry: int
    segments: Tuple[MemorySegment, ...]

    def __post_init__(self):
        _integer(self.entry, 0, MAX_WORD, "entry address")
        if type(self.segments) is not tuple or any(
                not isinstance(segment, MemorySegment) for segment in self.segments):
            raise MemoryImageError("image segments must be a tuple of MemorySegment records")


def image_to_data(image: MemoryImage) -> str:
    """Export canonical .data with the reference assembler's CRLF endings."""
    if not isinstance(image, MemoryImage):
        raise MemoryImageError("expected a MemoryImage")
    lines = ["ENTRY_ADDRESS:%d" % image.entry]
    for segment in image.segments:
        lines.extend(("%s:%d" % (_HEADERS[segment.kind], segment.index),
                      "offset:%d" % segment.offset,
                      "len:%d" % len(segment.words)))
        lines.extend(str(word) for word in segment.words)
    lines.append("END")
    return "\r\n".join(lines) + "\r\n"


def parse_data_to_image(source: str) -> MemoryImage:
    """Read a canonical .data export, rejecting truncated or unknown records.

    The historical permissive reader remains available as
    ``mc2mb._Assembler.memory_init_code1`` and ``mc2mb.data_to_mb``.
    """
    lines = source.splitlines()
    if not lines or not lines[0].startswith("ENTRY_ADDRESS:"):
        raise MemoryImageError("data image must begin with ENTRY_ADDRESS")
    try:
        entry = int(lines[0].split(":", 1)[1])
        segments = []
        position = 1
        while position < len(lines) and lines[position] != "END":
            header, index = lines[position].split(":", 1)
            if header not in _KINDS:
                raise MemoryImageError("unknown data segment %r" % header)
            if position + 2 >= len(lines):
                raise MemoryImageError("truncated data segment header")
            offset_line, length_line = lines[position + 1:position + 3]
            if not offset_line.startswith("offset:") or not length_line.startswith("len:"):
                raise MemoryImageError("data segment requires offset and len")
            offset, length = int(offset_line[7:]), int(length_line[4:])
            if length < 0 or position + 3 + length > len(lines):
                raise MemoryImageError("invalid or truncated data segment length")
            words = tuple(int(word) for word in lines[position + 3:position + 3 + length])
            segments.append(MemorySegment(_KINDS[header], int(index), offset, words))
            position += 3 + length
        if position != len(lines) - 1 or lines[position] != "END":
            raise MemoryImageError("data image must end with END")
        return MemoryImage(entry, tuple(segments))
    except (ValueError, IndexError) as exc:
        if isinstance(exc, MemoryImageError):
            raise
        raise MemoryImageError("invalid data image: %s" % exc) from exc


__all__ = ["MemoryImage", "MemorySegment", "MemoryImageError",
           "image_to_data", "parse_data_to_image"]
