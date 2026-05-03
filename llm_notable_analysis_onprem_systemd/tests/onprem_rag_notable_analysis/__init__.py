from pkgutil import extend_path

import _bootstrap  # noqa: F401

__path__ = extend_path(__path__, __name__)
