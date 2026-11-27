"""Water habituation with the current visual-task Uno sketch, controlled over SSH.

Run: python3 habituation.py --port /dev/ttyACM0 --mouse-id NPY195_2
Type start (or 2) to begin, stop (or 4) to abort, q to quit.
"""
from visualcue.habituation import main


if __name__ == "__main__":
    raise SystemExit(main())
