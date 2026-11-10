"""Allow ``python -m plx`` as an alias for the ``plx`` entry point."""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
