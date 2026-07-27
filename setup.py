from pathlib import Path
import re

from setuptools import find_packages, setup


ROOT = Path(__file__).resolve().parent
MODEL = ROOT / "sprout_core" / "model.py"
README = ROOT / "README.md"


def read_version() -> str:
    match = re.search(r'^SPROUT_VERSION = "([^"]+)"$', MODEL.read_text(encoding="utf-8"), re.MULTILINE)
    if not match:
        raise RuntimeError("Could not determine Sprout version")
    return match.group(1)


setup(
    name="sprout-language",
    version=read_version(),
    description="The Sprout programming language, runtime, tooling, and package ecosystem",
    long_description=README.read_text(encoding="utf-8"),
    long_description_content_type="text/markdown",
    python_requires=">=3.9",
    author="Sprout contributors",
    license="Apache-2.0",
    url="https://github.com/jerry5678912/Sprout",
    project_urls={
        "Documentation": "https://github.com/jerry5678912/Sprout/blob/main/docs/MANUAL.md",
        "Repository": "https://github.com/jerry5678912/Sprout.git",
        "Issues": "https://github.com/jerry5678912/Sprout/issues",
        "Changelog": "https://github.com/jerry5678912/Sprout/blob/main/CHANGELOG.md",
    },
    keywords=["programming-language", "interpreter", "bytecode", "lsp", "education"],
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Environment :: Console",
        "Intended Audience :: Developers",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Software Development :: Compilers",
        "Topic :: Software Development :: Interpreters",
    ],
    packages=find_packages(include=["sprout_core", "sprout_core.*"]),
    py_modules=["sprout"],
    package_data={"sprout_core": ["conformance/*.json", "conformance/*.sprout", "language_packs/*.json", "stdlib/*.sprout"]},
    include_package_data=True,
    entry_points={"console_scripts": ["sprout=sprout_core.cli:entrypoint"]},
    license_files=("LICENSE", "NOTICE"),
)
