"""
Shared test fixtures for the license-comply test suite.

This file is special to pytest: any "fixtures" defined here are automatically
available to ALL test files in this directory without needing to import them.

A fixture is a reusable piece of test setup. For example, if many tests need
a sample list of packages or a temporary requirements.txt file, we define
that setup once here and every test can use it by name.

Fixtures will be added here as we build each module (steps 5-11).
"""

# Fixtures will be added as we build each module. Examples of what will go here:
#
# @pytest.fixture
# def sample_packages():
#     """A list of PackageInfo objects for testing."""
#     ...
#
# @pytest.fixture
# def temp_requirements_file(tmp_path):
#     """A temporary requirements.txt file for testing the scanner."""
#     ...
#
# @pytest.fixture
# def sample_scan_result():
#     """A complete ScanResult for testing the reporter."""
#     ...
