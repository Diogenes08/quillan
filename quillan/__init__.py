"""Quillan2 — filesystem-driven AI story generation engine."""

try:
    from importlib.metadata import version, PackageNotFoundError
    try:
        __version__ = version("quillan")
    except PackageNotFoundError:
        __version__ = "1.0.0"  # fallback for editable installs without metadata
except ImportError:
    __version__ = "1.0.0"
