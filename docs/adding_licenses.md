# Adding a New License to the Knowledge Base

This guide walks you through adding a new license to license-comply's knowledge base. After following these steps, the tool will be able to recognize, classify, and analyze the license in compliance reports.

## Where the file lives

All license definitions are in a single YAML file:

```
src/license_comply/knowledge/licenses.yaml
```

The top of the file contains detailed schema documentation (lines 1-50). Read that first — it explains every field and every valid value.

## The 6 required fields

Each license entry has six fields:

| Field | Type | Description |
|---|---|---|
| `spdx_id` | string | The standardized [SPDX identifier](https://spdx.org/licenses/) (e.g., `"MIT"`, `"GPL-3.0-only"`) |
| `names` | list of strings | All known string variations the tool should recognize. Include the SPDX ID itself, the full human-readable name, and any common aliases found in PyPI metadata or classifier strings. |
| `category` | string | The license's legal category (see valid values below) |
| `summary` | string | A plain-English explanation of what this license means. Write for a non-lawyer audience. |
| `obligations` | list of objects | What a user must do to comply. Each obligation has a `text` (description) and a `category` (see below). |
| `risks` | list of strings | Potential legal pitfalls to watch out for when using software under this license. |

## Valid categories

### License categories

| Category | Meaning |
|---|---|
| `permissive` | Minimal restrictions. Users can do almost anything. |
| `weak_copyleft` | Copyleft applies to the library itself but not your whole project. |
| `strong_copyleft` | Copyleft applies to your entire project if you distribute it. |
| `public_domain` | No copyright restrictions at all. |
| `non_software` | Designed for creative works, not software. Use in code is unusual. |
| `proprietary` | Not an open-source license. |

### Obligation categories

| Category | Meaning | Example |
|---|---|---|
| `notice` | Include copyright notices, license text, give attribution | "Include copyright notice and license text in distributions" |
| `disclosure` | State or document modifications, mark altered versions | "Document all modifications to the original source code" |
| `source_sharing` | Share source code, copyleft distribution requirements | "Distribute complete corresponding source code with any binary distribution" |
| `use_restriction` | Endorsement restrictions, misrepresentation prohibitions | "Do not use contributor names for endorsement without permission" |
| `technical` | Linking requirements, installation instructions | "Provide installation information for user-installable devices" |

## Step-by-step instructions

### 1. Find the right section

Licenses are grouped by category in the YAML file. Find the section that matches your license's category:

- Permissive licenses are near the top
- Weak copyleft licenses come next
- Strong copyleft licenses follow
- Public domain, non-software, and proprietary are at the end

### 2. Copy an existing entry

Find an existing license in the same category and copy its entire block. For example, if you're adding a permissive license, copy the MIT entry as a starting point.

### 3. Fill in the fields

Here's a concrete example — the ISC license entry:

```yaml
  - spdx_id: "ISC"
    names:
      - "ISC"
      - "ISC License"
      - "ISC license (ISCL)"
    category: "permissive"
    summary: >
      A permissive license functionally equivalent to the BSD 2-Clause license.
      It allows use, copying, modification, and distribution for any purpose,
      as long as the copyright notice and license text are preserved.
    obligations:
      - text: "Include copyright notice and license text in distributions"
        category: "notice"
    risks:
      - "Functionally identical to BSD-2-Clause but less widely recognized, which can cause confusion during compliance audits"
```

Key formatting notes:
- Each entry starts with `- spdx_id:` (note the leading `- ` for the YAML list)
- The `summary` field uses `>` for a folded block scalar (long text that wraps)
- Obligations are a list of objects, each with `text` and `category`
- Risks are a simple list of strings

### 4. Add name variations

The `names` list is critical for matching. Include:
- The SPDX identifier exactly as written (e.g., `"GPL-3.0-only"`)
- The full human-readable name (e.g., `"GNU General Public License v3.0 only"`)
- Common aliases (e.g., `"GPL-3.0"`, `"GPLv3"`)
- Strings found in PyPI classifier metadata (e.g., `"License :: OSI Approved :: GNU General Public License v3 (GPLv3)"`)

The more name variations you include, the more packages the tool can classify correctly.

### 5. Update the tests

Two test files need updating:

**`tests/test_knowledge.py`** — Update the license count:

Find the test `test_licenses_yaml_has_expected_count` and increment the expected count (currently 42). Update the docstring to explain the new total.

```python
def test_licenses_yaml_has_expected_count(self) -> None:
    """We should have all 43 licenses defined.  # <-- update this number
    ...plus 1 more (YOUR-LICENSE) = 43 total.   # <-- add explanation
    """
    data = _load_yaml("licenses.yaml")
    licenses = data["licenses"]
    assert len(licenses) == 43, (  # <-- update this number
```

**`tests/test_classifier.py`** — Add a classification test:

Add a test that verifies your license is correctly classified. The test name should read like a sentence:

```python
def test_isc_classified_as_permissive(self) -> None:
    """ISC should be classified as permissive."""
    result = classify_license("ISC")
    assert result is not None
    assert result.spdx_id == "ISC"
    assert result.category == "permissive"
```

### 6. Run the tests

```bash
# Run knowledge base tests (validates YAML structure and counts)
pytest tests/test_knowledge.py -v

# Run classifier tests (validates license matching)
pytest tests/test_classifier.py -v

# Run the full suite to make sure nothing else broke
pytest tests/ -v
```

All tests should pass before submitting your PR.

## Checklist

Before submitting a pull request with a new license:

- [ ] Used the correct SPDX identifier from [spdx.org/licenses](https://spdx.org/licenses/)
- [ ] Included all known name variations in the `names` list
- [ ] Used one of the six valid categories
- [ ] Wrote a clear, non-technical summary
- [ ] Each obligation has both `text` and `category` fields
- [ ] Obligation categories are from the valid set (notice, disclosure, source_sharing, use_restriction, technical)
- [ ] Risks describe concrete compliance pitfalls
- [ ] Updated the license count in `test_licenses_yaml_has_expected_count`
- [ ] Added a classification test in `test_classifier.py`
- [ ] All tests pass (`pytest tests/ -v`)
