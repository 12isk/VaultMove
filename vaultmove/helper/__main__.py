import os
import sys

if not __package__:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from vaultmove.helper.server import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
