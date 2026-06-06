# Security Policy

Please report security issues privately to the project maintainers. Do not publish exploit details before a fix is available.

Do not include registry tokens, private package contents, or other credentials
in a public report. Include the Sprout version, operating system, minimal
reproduction, and any fuzz seed involved.

Maintainers run:

```sh
python3 tests/security.py
python3 sprout.py conformance
python3 sprout.py fuzz --iterations 500 --seed 20260606
```

The built-in registry is intended to run behind HTTPS. Publish tokens are stored
as SHA-256 digests and may be package-scoped and revoked. Package publishing and
installation reject path traversal and symbolic links, verify checksums, and
enforce download, file-count, and expanded-size limits.
