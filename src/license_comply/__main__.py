"""
Entry point for running license-comply as a Python module.

This file is what makes `python -m license_comply` work. When Python sees
`python -m some_package`, it looks for a __main__.py file inside that package
and runs it.

This is an alternative to using the `license-comply` command directly.
Both do the same thing — they call the main() function in cli.py.
"""

from license_comply.cli import main

# This block runs when the file is executed directly (python -m license_comply).
# The `if __name__ == "__main__"` pattern is a Python convention that means
# "only run this code if this file is the main program, not if it's imported."
if __name__ == "__main__":
    main()
