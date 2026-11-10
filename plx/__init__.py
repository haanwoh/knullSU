"""PocketLinux — a real Linux workstation inside your own Android phone.

The package is deliberately stdlib-only: it has to run inside Termux where
installing wheels is slow, and it must never break because of a dependency
bump. Everything lives behind one CLI entry point: ``plx``.
"""

__version__ = "1.0.0"
__all__ = ["__version__", "APP_NAME", "APP_TAGLINE"]

APP_NAME = "PocketLinux"
APP_TAGLINE = "ground-level Linux control for the phone in your pocket"
