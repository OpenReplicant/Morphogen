"""Entity resolution behind one interface (er.base.Resolver), with swappable backends."""

from . import settings
from .backends.overlap import Overlap
from .backends.tfidf import TfIdf
from .base import Resolver

BACKENDS = {"overlap": Overlap, "tfidf": TfIdf}


def make(backend: str | None = None) -> Resolver:
    return BACKENDS[backend or settings.BACKEND]()


__all__ = ["BACKENDS", "Resolver", "make", "settings"]
