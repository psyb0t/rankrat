# Third-party licenses

rankrat's own source is [WTFPL](LICENSE). The published Docker image also
contains its Python runtime dependencies, which keep their own licenses. This
file records them.

Nothing here restricts what you may do with rankrat itself. It exists because
two of the bundled packages ask for something in return for redistribution, and
shipping them inside an image is redistribution.

## The two that impose obligations

| Package | License | What it requires |
|---|---|---|
| [`certifi`](https://pypi.org/project/certifi/) | MPL-2.0 | File-level copyleft. The files stay under MPL-2.0 and recipients must be able to obtain their source; the license explicitly does not extend to the larger work it is combined with. Source: <https://github.com/certifi/python-certifi>. |
| [`python-multipart`](https://pypi.org/project/python-multipart/) | Apache-2.0 | Preserve the copyright and license notice. Source: <https://github.com/Kludex/python-multipart>. |

Both are unmodified upstream releases, installed from PyPI at the versions
pinned in `uv.lock`. rankrat does not patch or vendor either one, so the
upstream repositories above are the source form.

## Everything else in the image

The remaining runtime dependencies are permissive and impose no obligation
beyond keeping their notices, which the installed distributions carry in their
own `.dist-info` directories inside the image.

| License | Packages |
|---|---|
| MIT | annotated-doc, annotated-types, anyio, attrs, fastapi, h11, httpx-sse, jsonschema, jsonschema-specifications, mcp, pydantic, pydantic-core, pydantic-settings, pyjwt, python-dotenv, referencing, rpds-py, sse-starlette |
| BSD-3-Clause / BSD | certifi's peers: click, colorama, httpcore, httpx, idna, pyyaml, starlette, typing-inspection, uvicorn |
| PSF | pywin32 (Windows-only, not installed in the Linux image), typing-extensions |

## Regenerating this list

The set above is the runtime closure — the direct dependencies in
`pyproject.toml` plus everything they pull in, excluding the dev group, which
does not ship. It is derived from `uv.lock`, so it changes only when the lockfile
does. Re-check it after any dependency change that adds or replaces a package,
and confirm the license of anything new before it lands.
