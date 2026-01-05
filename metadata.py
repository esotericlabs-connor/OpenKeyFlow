"""Metadata loader for OpenKeyFlow."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

import tomllib

_METADATA_CACHE: Dict[str, Any] | None = None


def _resource_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parents[1]


def metadata_path() -> Path:
    return _resource_root() / "openkeyflow.toml"


def load_metadata() -> Dict[str, Any]:
    global _METADATA_CACHE
    if _METADATA_CACHE is not None:
        return _METADATA_CACHE
    path = metadata_path()
    try:
        with path.open("rb") as handle:
            _METADATA_CACHE = tomllib.load(handle)
    except FileNotFoundError:
        _METADATA_CACHE = {}
    return _METADATA_CACHE


def _project_metadata() -> Dict[str, Any]:
    data = load_metadata().get("project", {})
    if isinstance(data, dict):
        return dict(data)
    return {}


def project_name(default: str = "OpenKeyFlow") -> str:
    return str(_project_metadata().get("name", default))


def project_version(default: str = "0.0.0") -> str:
    return str(_project_metadata().get("version", default))


def project_description(default: str = "") -> str:
    return str(_project_metadata().get("description", default))


def project_authors() -> List[Dict[str, str]]:
    authors = _project_metadata().get("authors", [])
    if isinstance(authors, list):
        return [dict(author) for author in authors if isinstance(author, dict)]
    return []


def project_author(default: str = "OpenKeyFlow") -> str:
    authors = project_authors()
    if authors:
        name = authors[0].get("name")
        if name:
            return str(name)
    return default


def project_keywords() -> List[str]:
    keywords = _project_metadata().get("keywords", [])
    if isinstance(keywords, list):
        return [str(keyword) for keyword in keywords]
    return []


def project_classifiers() -> List[str]:
    classifiers = _project_metadata().get("classifiers", [])
    if isinstance(classifiers, list):
        return [str(classifier) for classifier in classifiers]
    return []


def project_urls() -> Dict[str, str]:
    urls = _project_metadata().get("urls", {})
    if isinstance(urls, dict):
        return {str(key): str(value) for key, value in urls.items()}
    return {}


def project_license(default: str = "") -> str:
    return str(_project_metadata().get("license", default))


PROJECT_NAME = project_name()
PROJECT_VERSION = project_version()
PROJECT_DESCRIPTION = project_description()
PROJECT_AUTHORS = project_authors()
PROJECT_KEYWORDS = project_keywords()
PROJECT_CLASSIFIERS = project_classifiers()
PROJECT_URLS = project_urls()
PROJECT_LICENSE = project_license()

__version__ = PROJECT_VERSION

__all__ = [
    "PROJECT_AUTHORS",
    "PROJECT_CLASSIFIERS",
    "PROJECT_DESCRIPTION",
    "PROJECT_KEYWORDS",
    "PROJECT_LICENSE",
    "PROJECT_NAME",
    "PROJECT_URLS",
    "PROJECT_VERSION",
    "__version__",
    "load_metadata",
    "metadata_path",
    "project_author",
    "project_authors",
    "project_classifiers",
    "project_description",
    "project_keywords",
    "project_license",
    "project_name",
    "project_urls",
    "project_version",
]