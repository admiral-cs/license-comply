"""
Tests for the resolver module (PyPI license lookup).

These tests verify that the resolver correctly queries PyPI, handles errors,
uses the disk cache, and performs parallel lookups. We use the `responses`
library to mock HTTP requests — this means tests never actually hit PyPI,
making them fast, reliable, and runnable offline.

The `responses` library works by intercepting HTTP requests made by the
`requests` library and returning pre-defined responses instead.
"""

from __future__ import annotations

import json
import os
import time
from unittest.mock import patch

import responses

from license_comply.models import PackageInfo
from license_comply.resolver import (
    CACHE_TTL_SECONDS,
    _save_cache,
    resolve_licenses,
)

# ---------------------------------------------------------------------------
# Helper: build a fake PyPI API response
# ---------------------------------------------------------------------------


def _make_pypi_response(
    package_name: str,
    license_field: str = "MIT License",
    classifiers: list[str] | None = None,
) -> dict:
    """Build a fake PyPI JSON API response for testing.

    Args:
        package_name: The package name.
        license_field: The value for info.license.
        classifiers: The list of classifiers. Defaults to empty.

    Returns:
        A dict mimicking the PyPI JSON API response structure.
    """
    if classifiers is None:
        classifiers = []
    return {
        "info": {
            "name": package_name,
            "license": license_field,
            "classifiers": classifiers,
            "project_urls": {
                "Homepage": f"https://github.com/user/{package_name}",
            },
        },
    }


# ===========================================================================
# Tests for basic resolution
# ===========================================================================


class TestBasicResolution:
    """Tests for resolving licenses from PyPI."""

    @responses.activate
    def test_resolves_license_from_pypi(self) -> None:
        """Should fetch and return the license from PyPI's JSON API."""
        responses.add(
            responses.GET,
            "https://pypi.org/pypi/requests/json",
            json=_make_pypi_response("requests", license_field="Apache 2.0"),
            status=200,
        )

        packages = [PackageInfo(name="requests")]
        results = resolve_licenses(packages, use_cache=False)

        assert len(results) == 1
        assert results[0].package_name == "requests"
        assert results[0].declared_license == "Apache 2.0"

    @responses.activate
    def test_prefers_classifier_over_license_field(self) -> None:
        """When both license field and classifier exist, prefer classifier."""
        responses.add(
            responses.GET,
            "https://pypi.org/pypi/flask/json",
            json=_make_pypi_response(
                "flask",
                license_field="BSD-3-Clause",
                classifiers=["License :: OSI Approved :: BSD License"],
            ),
            status=200,
        )

        packages = [PackageInfo(name="flask")]
        results = resolve_licenses(packages, use_cache=False)

        assert results[0].declared_license == "License :: OSI Approved :: BSD License"

    @responses.activate
    def test_uses_license_expression_field(self) -> None:
        """Should use the PEP 639 license_expression field when available.

        Many modern packages (flask, click, pydantic, etc.) have migrated to
        the newer license_expression field, which contains a proper SPDX
        expression. When license and classifiers are empty but
        license_expression is set, the resolver should use it.
        """
        responses.add(
            responses.GET,
            "https://pypi.org/pypi/flask/json",
            json={
                "info": {
                    "name": "flask",
                    "license": None,
                    "license_expression": "BSD-3-Clause",
                    "classifiers": [],
                    "project_urls": {},
                },
            },
            status=200,
        )

        packages = [PackageInfo(name="flask")]
        results = resolve_licenses(packages, use_cache=False)

        assert results[0].declared_license == "BSD-3-Clause"

    @responses.activate
    def test_license_expression_preferred_over_classifier(self) -> None:
        """license_expression should take priority over classifiers.

        The license_expression field is the most standardized format (proper
        SPDX), so when both it and classifiers are present, we prefer
        license_expression.
        """
        responses.add(
            responses.GET,
            "https://pypi.org/pypi/some-pkg/json",
            json={
                "info": {
                    "name": "some-pkg",
                    "license": "MIT License",
                    "license_expression": "MIT",
                    "classifiers": [
                        "License :: OSI Approved :: MIT License",
                    ],
                    "project_urls": {},
                },
            },
            status=200,
        )

        packages = [PackageInfo(name="some-pkg")]
        results = resolve_licenses(packages, use_cache=False)

        # Should use the clean SPDX expression, not the verbose classifier
        assert results[0].declared_license == "MIT"

    @responses.activate
    def test_handles_missing_package_gracefully(self) -> None:
        """Should return None license for packages not found on PyPI."""
        responses.add(
            responses.GET,
            "https://pypi.org/pypi/nonexistent-pkg-xyz/json",
            status=404,
        )

        packages = [PackageInfo(name="nonexistent-pkg-xyz")]
        results = resolve_licenses(packages, use_cache=False)

        assert len(results) == 1
        assert results[0].package_name == "nonexistent-pkg-xyz"
        assert results[0].declared_license is None

    @responses.activate
    def test_handles_network_error_gracefully(self) -> None:
        """Should not crash on network errors — returns None license instead."""
        responses.add(
            responses.GET,
            "https://pypi.org/pypi/some-package/json",
            body=ConnectionError("Network unreachable"),
        )

        packages = [PackageInfo(name="some-package")]
        results = resolve_licenses(packages, use_cache=False)

        assert len(results) == 1
        assert results[0].declared_license is None

    @responses.activate
    def test_parallel_lookups_return_all_results(self) -> None:
        """Parallel lookups should return results for every package."""
        for name in ["pkg-a", "pkg-b", "pkg-c"]:
            responses.add(
                responses.GET,
                f"https://pypi.org/pypi/{name}/json",
                json=_make_pypi_response(name, license_field="MIT"),
                status=200,
            )

        packages = [
            PackageInfo(name="pkg-a"),
            PackageInfo(name="pkg-b"),
            PackageInfo(name="pkg-c"),
        ]
        results = resolve_licenses(packages, use_cache=False)

        assert len(results) == 3
        result_names = {r.package_name for r in results}
        assert result_names == {"pkg-a", "pkg-b", "pkg-c"}

    @responses.activate
    def test_extracts_source_url(self) -> None:
        """Should extract the source repository URL from project_urls."""
        responses.add(
            responses.GET,
            "https://pypi.org/pypi/click/json",
            json={
                "info": {
                    "name": "click",
                    "license": "BSD-3-Clause",
                    "classifiers": [],
                    "project_urls": {
                        "Source Code": "https://github.com/pallets/click",
                        "Documentation": "https://click.palletsprojects.com",
                    },
                },
            },
            status=200,
        )

        packages = [PackageInfo(name="click")]
        results = resolve_licenses(packages, use_cache=False)

        assert results[0].source_url == "https://github.com/pallets/click"


# ===========================================================================
# Tests for disk caching
# ===========================================================================


class TestDiskCache:
    """Tests for the disk cache that avoids redundant PyPI requests."""

    @responses.activate
    def test_cache_avoids_duplicate_requests(self, tmp_path) -> None:
        """A cached package should not trigger a new PyPI request."""
        # Pre-populate the cache
        cache_data = {
            "requests": {
                "declared_license": "Apache 2.0",
                "pypi_url": "https://pypi.org/project/requests/",
                "source_url": None,
                "timestamp": time.time(),  # Fresh cache entry
            }
        }
        cache_path = tmp_path / ".license-comply-cache.json"
        cache_path.write_text(json.dumps(cache_data))

        # No HTTP mocks registered — if the resolver tries to call PyPI, it will fail
        packages = [PackageInfo(name="requests")]
        results = resolve_licenses(packages, use_cache=True, cache_dir=str(tmp_path))

        assert len(results) == 1
        assert results[0].declared_license == "Apache 2.0"

    @responses.activate
    def test_cache_expires_after_ttl(self, tmp_path) -> None:
        """Expired cache entries should be refreshed from PyPI."""
        # Pre-populate cache with an expired entry
        expired_time = time.time() - CACHE_TTL_SECONDS - 100
        cache_data = {
            "flask": {
                "declared_license": "Old License",
                "pypi_url": "https://pypi.org/project/flask/",
                "source_url": None,
                "timestamp": expired_time,
            }
        }
        cache_path = tmp_path / ".license-comply-cache.json"
        cache_path.write_text(json.dumps(cache_data))

        # Register a mock for the fresh lookup
        responses.add(
            responses.GET,
            "https://pypi.org/pypi/flask/json",
            json=_make_pypi_response("flask", license_field="BSD-3-Clause"),
            status=200,
        )

        packages = [PackageInfo(name="flask")]
        results = resolve_licenses(packages, use_cache=True, cache_dir=str(tmp_path))

        assert results[0].declared_license == "BSD-3-Clause"

    @responses.activate
    def test_cache_handles_corrupted_file(self, tmp_path) -> None:
        """A corrupted cache file should be ignored, not crash the tool."""
        cache_path = tmp_path / ".license-comply-cache.json"
        cache_path.write_text("this is not valid json!!!")

        responses.add(
            responses.GET,
            "https://pypi.org/pypi/click/json",
            json=_make_pypi_response("click", license_field="BSD-3-Clause"),
            status=200,
        )

        packages = [PackageInfo(name="click")]
        results = resolve_licenses(packages, use_cache=True, cache_dir=str(tmp_path))

        # Should succeed despite corrupted cache
        assert len(results) == 1
        assert results[0].declared_license == "BSD-3-Clause"

    @responses.activate
    def test_new_results_are_cached(self, tmp_path) -> None:
        """After fetching from PyPI, results should be written to the cache."""
        responses.add(
            responses.GET,
            "https://pypi.org/pypi/rich/json",
            json=_make_pypi_response("rich", license_field="MIT"),
            status=200,
        )

        packages = [PackageInfo(name="rich")]
        resolve_licenses(packages, use_cache=True, cache_dir=str(tmp_path))

        # Verify the cache file was created with the result
        cache_path = tmp_path / ".license-comply-cache.json"
        assert cache_path.exists()
        cache_data = json.loads(cache_path.read_text())
        assert "rich" in cache_data
        assert cache_data["rich"]["declared_license"] == "MIT"


# ===========================================================================
# Tests for edge cases
# ===========================================================================


class TestEdgeCases:
    """Tests for resolver edge cases — unusual PyPI responses and errors.

    These tests verify that the resolver gracefully handles situations
    like empty metadata, HTTP errors, and the special "UNKNOWN" license
    value that older packages sometimes report.
    """

    @responses.activate
    def test_empty_license_metadata_returns_none(self) -> None:
        """A PyPI response with empty license, no classifiers, and no license_expression
        should return declared_license=None (we don't know the license).
        """
        responses.add(
            responses.GET,
            "https://pypi.org/pypi/mystery-pkg/json",
            json={
                "info": {
                    "name": "mystery-pkg",
                    "license": "",
                    "classifiers": [],
                    "project_urls": {},
                },
            },
            status=200,
        )

        packages = [PackageInfo(name="mystery-pkg")]
        results = resolve_licenses(packages, use_cache=False)

        assert len(results) == 1
        assert results[0].package_name == "mystery-pkg"
        assert results[0].declared_license is None

    @responses.activate
    def test_http_500_returns_none_license(self) -> None:
        """An HTTP 500 from PyPI should return declared_license=None without crashing."""
        responses.add(
            responses.GET,
            "https://pypi.org/pypi/server-error-pkg/json",
            status=500,
        )

        packages = [PackageInfo(name="server-error-pkg")]
        results = resolve_licenses(packages, use_cache=False)

        assert len(results) == 1
        assert results[0].package_name == "server-error-pkg"
        assert results[0].declared_license is None

    @responses.activate
    def test_license_field_literally_unknown_treated_as_none(self) -> None:
        """A PyPI response with license='UNKNOWN' should return declared_license=None.

        Older packages on PyPI often have the literal string 'UNKNOWN' as their
        license value when the author didn't specify one. The resolver should
        treat this the same as having no license.
        """
        responses.add(
            responses.GET,
            "https://pypi.org/pypi/old-pkg/json",
            json={
                "info": {
                    "name": "old-pkg",
                    "license": "UNKNOWN",
                    "classifiers": [],
                    "project_urls": {},
                },
            },
            status=200,
        )

        packages = [PackageInfo(name="old-pkg")]
        results = resolve_licenses(packages, use_cache=False)

        assert len(results) == 1
        assert results[0].package_name == "old-pkg"
        assert results[0].declared_license is None


# ===========================================================================
# Tests for cache cleanup on error (Fix 1.1)
# ===========================================================================


class TestCacheCleanupOnError:
    """Tests for the NameError fix in _save_cache().

    Previously, if json.dump() raised an OSError (e.g., disk full), the
    except handler would crash with NameError because tmp_path hadn't been
    assigned yet. The fix ensures tmp_path is assigned before json.dump()
    and guarded with a None check in the except handler.
    """

    def test_save_cache_handles_oserror_without_name_error(self, tmp_path) -> None:
        """_save_cache should not crash with NameError when json.dump fails."""
        cache_path = str(tmp_path / ".license-comply-cache.json")
        cache_data = {
            "requests": {
                "declared_license": "MIT",
                "pypi_url": "https://pypi.org/project/requests/",
                "source_url": None,
                "timestamp": time.time(),
            }
        }

        # Mock json.dump to raise OSError (simulating disk full)
        with patch("license_comply.resolver.json.dump", side_effect=OSError("disk full")):
            # This should NOT raise NameError — it should handle the error gracefully
            _save_cache(cache_data, cache_path)

        # The cache file should NOT have been created (the write failed)
        assert not os.path.isfile(cache_path)

    def test_save_cache_cleans_up_temp_file_on_error(self, tmp_path) -> None:
        """When os.replace fails, the temp file should be cleaned up."""
        cache_path = str(tmp_path / ".license-comply-cache.json")
        cache_data = {
            "pkg": {
                "declared_license": "MIT",
                "pypi_url": None,
                "source_url": None,
                "timestamp": time.time(),
            }
        }

        # Mock os.replace to raise OSError (simulating permission error)
        with patch("license_comply.resolver.os.replace", side_effect=OSError("permission denied")):
            _save_cache(cache_data, cache_path)

        # The temp file should have been cleaned up
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert len(tmp_files) == 0, "Temp file was not cleaned up after os.replace failure"


# ===========================================================================
# Tests for future cache timestamp validation (Fix 2.4)
# ===========================================================================


class TestFutureCacheTimestamp:
    """Tests for the future timestamp fix in _get_cached_entry().

    A cache entry with a timestamp in the future should be treated as
    expired, not as a valid cache hit that never expires.
    """

    @responses.activate
    def test_future_timestamp_treated_as_expired(self, tmp_path) -> None:
        """A cache entry with a future timestamp should trigger a fresh PyPI lookup."""
        # Pre-populate cache with a future timestamp (e.g., year 2099)
        future_time = time.time() + 365 * 24 * 60 * 60  # 1 year in the future
        cache_data = {
            "flask": {
                "declared_license": "Stale License",
                "pypi_url": "https://pypi.org/project/flask/",
                "source_url": None,
                "timestamp": future_time,
            }
        }
        cache_path = tmp_path / ".license-comply-cache.json"
        cache_path.write_text(json.dumps(cache_data))

        # Register a mock for the fresh lookup
        responses.add(
            responses.GET,
            "https://pypi.org/pypi/flask/json",
            json=_make_pypi_response("flask", license_field="BSD-3-Clause"),
            status=200,
        )

        packages = [PackageInfo(name="flask")]
        results = resolve_licenses(packages, use_cache=True, cache_dir=str(tmp_path))

        # Should have fetched fresh data, not used the stale cache entry
        assert results[0].declared_license == "BSD-3-Clause"


# ===========================================================================
# Tests for cache pruning (Fix 3.1)
# ===========================================================================


class TestCachePruning:
    """Tests that expired entries are pruned when the cache is saved."""

    @responses.activate
    def test_expired_entries_pruned_on_save(self, tmp_path) -> None:
        """Expired cache entries should be removed when the cache is saved."""
        # Pre-populate cache with one expired and one fresh entry
        expired_time = time.time() - CACHE_TTL_SECONDS - 100
        cache_data = {
            "old-pkg": {
                "declared_license": "MIT",
                "pypi_url": None,
                "source_url": None,
                "timestamp": expired_time,
            },
            "new-pkg": {
                "declared_license": "MIT",
                "pypi_url": None,
                "source_url": None,
                "timestamp": time.time(),
            },
        }
        cache_path = tmp_path / ".license-comply-cache.json"
        cache_path.write_text(json.dumps(cache_data))

        # Register a mock so we can trigger a save by resolving a new package
        responses.add(
            responses.GET,
            "https://pypi.org/pypi/fresh-pkg/json",
            json=_make_pypi_response("fresh-pkg", license_field="MIT"),
            status=200,
        )

        packages = [PackageInfo(name="fresh-pkg")]
        resolve_licenses(packages, use_cache=True, cache_dir=str(tmp_path))

        # Read back the cache — the expired "old-pkg" should be gone.
        # Note: cache keys are now normalized (hyphens → underscores, lowercase)
        # per PEP 503, so "fresh-pkg" is stored as "fresh_pkg".
        saved_cache = json.loads(cache_path.read_text())
        assert "old-pkg" not in saved_cache, "Expired entry should have been pruned"
        assert "new-pkg" in saved_cache, "Fresh entry should still be in cache"
        assert "fresh_pkg" in saved_cache, "Newly fetched entry should be in cache"
