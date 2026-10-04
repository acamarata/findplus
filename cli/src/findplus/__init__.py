from importlib.metadata import PackageNotFoundError, version

from findplus._bundle_version import bundle_version

try:
    __version__ = bundle_version() or version("findplus")
except PackageNotFoundError:
    __version__ = "1.0.0.dev0"
