"""Alias for the Pi display + Arduino logger; run only one entry point."""
from visualcue.runner import main

if __name__ == "__main__":
    raise SystemExit(main())
