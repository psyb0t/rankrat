# Third-party licenses

Rankrat's own source is [WTFPL](LICENSE). This document records the complete
Python-package closure installed in the production image by the current
`uv.lock`; it excludes Rankrat itself and OS packages supplied by the Python
base image.

The inventory below was verified from the Syft SBOM emitted by `make sbom` for
the production image. Re-run that target after every dependency or base-image
change and update this notice if the runtime package closure changes. Package
license texts and notices remain in their installed distribution metadata. This
is an attribution record, not legal advice.

## Runtime Python packages

| License | Packages |
| --- | --- |
| Apache-2.0 | python-multipart |
| Apache-2.0 OR BSD-3-Clause | cryptography |
| BSD-3-Clause | click, httpcore, httpx, idna, pycparser, python-dotenv, sse-starlette, starlette, uvicorn |
| MIT | annotated-doc, annotated-types, anyio, attrs, fastapi, h11, httpx-sse, jsonschema, jsonschema-specifications, mcp, pip, pydantic, pydantic-core, pydantic-settings, pyjwt, pyyaml, referencing, rpds-py, typing-inspection |
| MIT-0 | cffi |
| MPL-2.0 | certifi |
| PSF-2.0 | typing-extensions |

All listed packages are unmodified upstream releases selected by `uv.lock`.
For the source form of an individual package, use its PyPI project page or the
source-distribution URL and hash recorded beside that package in `uv.lock`.

## Notes on the non-permissive entries

- [`certifi`](https://pypi.org/project/certifi/) is MPL-2.0. Its file-level
  copyleft applies to its own covered files and does not automatically extend to
  the larger combined work. Its source is available from
  <https://github.com/certifi/python-certifi>.
- [`python-multipart`](https://pypi.org/project/python-multipart/) is
  Apache-2.0. Preserve its copyright and license notices when redistributing
  the image. Its source is available from <https://github.com/Kludex/python-multipart>.
- [`cryptography`](https://pypi.org/project/cryptography/) is dual licensed
  Apache-2.0 or BSD-3-Clause; its distribution contains the applicable notices.
