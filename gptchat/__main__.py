"""Allow ``python -m gptchat``."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
