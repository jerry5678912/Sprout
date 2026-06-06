# Security Policy

## Supported Versions

Sprout is currently alpha software. Security fixes are applied to the latest
release and the `main` branch. Older alpha releases may not receive patches.

## Reporting a Vulnerability

Do not open a public issue for a suspected vulnerability.

Use GitHub's **Report a vulnerability** flow under the repository Security tab:

<https://github.com/jerry5678912/Sprout/security/advisories/new>

Include:

- the affected Sprout version or commit;
- operating system and Python version;
- the smallest practical reproduction;
- impact and required attacker access;
- any malicious package/archive sample;
- a deterministic fuzz seed when relevant.

Do not include live registry tokens, private packages, personal data, or
unredacted credentials. Maintainers should acknowledge a complete report within
seven days and coordinate disclosure after a fix is available.

## Security Boundaries

- Sprout programs are not sandboxed. They can access files, networking, Python
  interop, and other capabilities granted to the host process.
- `importpython` executes Python code and should be treated as trusted-code
  interop.
- The built-in registry should run behind HTTPS and an authenticated reverse
  proxy for public deployments.
- Package downloads and extraction enforce path, symlink, file-count, expanded
  size, and checksum checks, but package signatures and a public trust service
  are not implemented yet.
- The VS Code extension launches the bundled/local Sprout runtime and should
  only be used with trusted workspaces.

## Maintainer Checks

```sh
python3 tests/security.py
python3 sprout.py conformance
python3 sprout.py fuzz --iterations 500 --seed 20260606
python3 sprout.py release-check
```
