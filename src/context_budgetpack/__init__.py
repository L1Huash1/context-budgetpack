"""Explicit local context bundles with exact UTF-8 byte budgets."""

from .core import BundleError, build_bundle, verify_bundle, write_bundle

__version__ = "0.1.0"
__all__ = ["BundleError", "build_bundle", "verify_bundle", "write_bundle", "__version__"]
