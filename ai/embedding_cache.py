"""Compact float64 vectors with a backward-compatible, atomic JSON cache.

Only the derived AI embedding cache is handled here. User state is never opened.
Decode one vector at a time so startup never materializes the whole JSON text or
the whole dictionary of Python float lists alongside the compact representation.
"""
from array import array
import json
import os
from pathlib import Path
import tempfile


class _ObjectReader:
    def __init__(self, stream, chunk_size=65536):
        if chunk_size <= 0:
            raise ValueError("Chunk size must be positive")
        self.stream = stream
        self.chunk_size = chunk_size
        self.buffer = ""
        self.eof = False
        self.decoder = json.JSONDecoder()

    def refill(self):
        chunk = self.stream.read(self.chunk_size)
        self.buffer += chunk
        self.eof = not chunk

    def whitespace(self):
        while True:
            self.buffer = self.buffer.lstrip(" \t\r\n")
            if self.buffer or self.eof:
                return
            self.refill()

    def expect(self, char):
        self.whitespace()
        if not self.buffer.startswith(char):
            raise ValueError("Invalid embedding cache JSON")
        self.buffer = self.buffer[1:]

    def value(self):
        self.whitespace()
        while True:
            try:
                value, end = self.decoder.raw_decode(self.buffer)
            except json.JSONDecodeError:
                if self.eof:
                    raise
                self.refill()
                continue
            self.buffer = self.buffer[end:]
            return value


def load_vectors(path, *, chunk_size=65536):
    """Read every cached vector, including historical keys, without changing disk."""
    result = {}
    with open(path, encoding="utf-8") as stream:
        reader = _ObjectReader(stream, chunk_size)
        reader.expect("{")
        reader.whitespace()
        if not reader.buffer.startswith("}"):
            while True:
                key = reader.value()
                if not isinstance(key, str):
                    raise ValueError("Embedding cache keys must be strings")
                reader.expect(":")
                values = reader.value()
                if not isinstance(values, list):
                    raise ValueError("Embedding vectors must be lists")
                result[key] = array("d", values)
                del values
                reader.whitespace()
                if reader.buffer.startswith("}"):
                    break
                reader.expect(",")
        reader.expect("}")
        reader.whitespace()
        if reader.buffer:
            raise ValueError("Trailing content in embedding cache")
    return result


def save_vectors(path, vectors):
    """Keep the legacy JSON shape and old file intact until replacement succeeds."""
    parent = Path(path).parent
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=parent,
            prefix=".embedding-cache-", suffix=".tmp", delete=False,
        ) as stream:
            temporary = stream.name
            stream.write("{")
            for index, (key, vector) in enumerate(vectors.items()):
                if index:
                    stream.write(", ")
                stream.write(json.dumps(key))
                stream.write(": ")
                # At most one vector becomes a temporary Python list.
                json.dump(list(vector), stream)
            stream.write("}")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            os.unlink(temporary)
