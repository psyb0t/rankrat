"""Rankrat package metadata."""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version

try:
    __version__ = package_version("rankrat")
except PackageNotFoundError:
    __version__ = "0.0.0+source"
