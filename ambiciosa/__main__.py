"""`python -m ambiciosa ...` is the same as the `ambiciosa` command."""

import sys

from .simulation.cli import main

if __name__ == "__main__":
    sys.exit(main())
