# Contributing to license-comply

Thanks for your interest in contributing! This guide covers everything you need to get started.

## Reporting Issues

- **Bug reports:** Include the Python version, OS, and the command you ran. Paste the full error output if possible.
- **Feature requests:** Describe the problem you're trying to solve, not just the solution you'd like. Context helps us design the right approach.
- **License data corrections:** If a license is misclassified or missing, open an issue with the license name, SPDX identifier, and a link to the license text.

## Submitting Pull Requests

1. Fork the repo and create a feature branch from `main`.
2. Make your changes (see coding standards below).
3. Add or update tests for any new functionality.
4. Run the full test and lint suite (see below) and make sure everything passes.
5. Write a clear PR description explaining **what** changed and **why**.

Keep PRs focused — one feature or fix per PR. This makes review faster for everyone.

## Development Setup

```bash
# Clone your fork
git clone https://github.com/YOUR_USERNAME/license-comply.git
cd license-comply

# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install in development mode with dev dependencies
pip install -e ".[dev]"
```

## Running Tests and Linting

All of these must pass before submitting a PR:

```bash
# Run the test suite
pytest tests/ -v

# Check for lint errors
ruff check src/ tests/

# Check formatting
ruff format --check src/ tests/

# Auto-format (if needed)
ruff format src/ tests/
```

You can also use `make test`, `make lint`, and `make format` as shortcuts.

## Coding Standards

- **Clarity over cleverness.** Three readable lines beat one clever one-liner.
- **Descriptive names.** `license_type` not `lt`. No abbreviations unless universally understood.
- **Docstrings on every function.** Explain what it does, its arguments, and what it returns.
- **Type hints** on all function signatures.
- **Comments** that explain *why*, not just *what*.
- **Python 3.9+ compatibility.** No `match`/`case` statements (3.10+), no `X | Y` union type syntax (3.10+). Use `if`/`elif` chains and `Optional[X]` or `Union[X, Y]` instead.
- **PEP 8** style with a max line length of 100 characters.
- **Error handling** should be user-friendly — plain English messages that explain what went wrong and what to do.

## Modifying the Knowledge Base

The YAML files in `src/license_comply/knowledge/` define the license database, compatibility rules, and default policies. If you're adding or correcting license data:

- Use the [SPDX identifier](https://spdx.org/licenses/) as the license key.
- Include all known aliases and classifier strings.
- Add tests in `tests/test_knowledge.py` and `tests/test_classifier.py` to verify matching.

For a detailed walkthrough, see [docs/adding_licenses.md](docs/adding_licenses.md).

## Legal Note

By submitting a contribution, you agree that your work will be licensed under the project's [Apache License 2.0](LICENSE).

## Questions?

Open an issue — we're happy to help.
