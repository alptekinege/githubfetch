#!/usr/bin/env python3
"""Compatibility shim: keeps ``python githubfetch.py <username>`` working.

The implementation now lives in the ``githubfetch`` package next to this file.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from githubfetch.cli import main  # noqa: E402

if __name__ == "__main__":
    main()
