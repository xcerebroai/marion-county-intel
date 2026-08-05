"""
Generic ArcGIS REST FeatureServer / MapServer query adapter.

Any county whose distress source is an ArcGIS Online or Portal-hosted
feature layer (mortgage foreclosure notices, sheriff sale calendars,
code-violation point layers, parcels, etc.) can drive its scraping
through this adapter. The adapter is county-agnostic: it takes a
service URL + layer ID + query parameters and returns an iterable
stream of normalized feature dicts.

Usage:

    from scaffold.scrapers._arcgis_featureserver import (
        ArcGISFeatureServer,
    )

    server = ArcGISFeatureServer(
        "https://maps.example.gov/arcgis/rest/services/Foo/MapServer",
        user_agent="xcerebro-county-foreclosure/0.1",
    )
    for feature in server.iter_features(layer_id=0):
        ...

Key contract:

  - Uses urllib only (no external deps) so the framework runs on a
    base Python install per knowledge_base/engineering/01_python_environment.md.
  - Honors maxRecordCount-driven pagination via resultOffset.
  - Retries transient HTTP errors with exponential backoff.
  - Returns a list of {"attributes": {...}, "geometry": {...}} dicts,
    each augmented with a stable `_object_id` shortcut.
  - Lets the caller pass a `fetch_fn` for testing (e.g. injecting
    fixture data instead of hitting the network).
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable, Iterator


DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_USER_AGENT = "xcerebro-county-framework/0.1"
DEFAULT_PAGE_SIZE = 1000
DEFAULT_MAX_RETRIES = 4
DEFAULT_BACKOFF_BASE_SECONDS = 0.5


@dataclass
class ArcGISServerError(Exception):
    """Raised when the ArcGIS REST endpoint returns an error envelope."""
    code: int
    message: str
    request_url: str

    def __str__(self) -> str:  # pragma: no cover — formatter
        return (
            f"ArcGIS error {self.code} at {self.request_url}: {self.message}"
        )


FetchFn = Callable[[str, dict], dict]
"""Signature: (request_url, params) -> JSON-decoded response dict."""


def _default_fetch(url: str, params: dict, *,
                   user_agent: str = DEFAULT_USER_AGENT,
                   timeout: int = DEFAULT_TIMEOUT_SECONDS,
                   max_retries: int = DEFAULT_MAX_RETRIES,
                   backoff_base: float = DEFAULT_BACKOFF_BASE_SECONDS) -> dict:
    """Real HTTP fetcher used in production. Injectable for tests."""
    qs = urllib.parse.urlencode(params, doseq=True)
    full_url = f"{url}?{qs}"
    last_err: Exception | None = None
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(
                full_url,
                headers={
                    "User-Agent": user_agent,
                    "Accept": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode("utf-8")
                data = json.loads(body)
                return data
        except urllib.error.HTTPError as e:
            last_err = e
            # 4xx (except 429) are caller errors — fail fast.
            if 400 <= e.code < 500 and e.code not in (408, 429):
                raise
            wait = backoff_base * (2 ** attempt)
            time.sleep(wait)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last_err = e
            wait = backoff_base * (2 ** attempt)
            time.sleep(wait)
    raise RuntimeError(
        f"ArcGIS fetch failed after {max_retries} attempts: {full_url}"
    ) from last_err


class ArcGISFeatureServer:
    """
    Wrapper for an ArcGIS REST FeatureServer or MapServer service.

    Construct with the service base URL (without trailing /query):

        srv = ArcGISFeatureServer("https://.../MapServer")

    Query layers via:

        for feature in srv.iter_features(layer_id=0, where="YEAR>=2026"):
            ...

    Each `feature` is a dict shaped:

        {
          "_object_id": int,        # convenience extract from attributes
          "attributes": { ... },    # all fields requested via out_fields
          "geometry": { ... },      # if return_geometry=True
        }
    """

    def __init__(self, service_url: str, *,
                 user_agent: str = DEFAULT_USER_AGENT,
                 fetch_fn: FetchFn | None = None,
                 page_size: int = DEFAULT_PAGE_SIZE,
                 timeout: int = DEFAULT_TIMEOUT_SECONDS):
        self.service_url = service_url.rstrip("/")
        self.user_agent = user_agent
        self.page_size = page_size
        self.timeout = timeout
        self._fetch_override = fetch_fn

    def _fetch(self, url: str, params: dict) -> dict:
        if self._fetch_override is not None:
            return self._fetch_override(url, params)
        return _default_fetch(url, params, user_agent=self.user_agent,
                               timeout=self.timeout)

    def describe_service(self) -> dict:
        return self._fetch(self.service_url, {"f": "pjson"})

    def describe_layer(self, layer_id: int) -> dict:
        layer_url = f"{self.service_url}/{layer_id}"
        return self._fetch(layer_url, {"f": "pjson"})

    def count_features(self, layer_id: int, where: str = "1=1") -> int:
        layer_url = f"{self.service_url}/{layer_id}/query"
        resp = self._fetch(layer_url, {
            "where": where,
            "returnCountOnly": "true",
            "f": "json",
        })
        if "error" in resp:
            err = resp["error"]
            raise ArcGISServerError(
                code=err.get("code", -1),
                message=err.get("message", "unknown"),
                request_url=layer_url,
            )
        return int(resp.get("count", 0))

    def iter_features(self, layer_id: int, *,
                      where: str = "1=1",
                      out_fields: str = "*",
                      return_geometry: bool = True,
                      page_size: int | None = None,
                      max_features: int | None = None) -> Iterator[dict]:
        """Yield features one at a time, transparently paginating."""
        page = page_size or self.page_size
        offset = 0
        emitted = 0
        layer_url = f"{self.service_url}/{layer_id}/query"
        while True:
            params = {
                "where": where,
                "outFields": out_fields,
                "returnGeometry": "true" if return_geometry else "false",
                "resultOffset": offset,
                "resultRecordCount": page,
                "f": "json",
            }
            resp = self._fetch(layer_url, params)
            if "error" in resp:
                err = resp["error"]
                raise ArcGISServerError(
                    code=err.get("code", -1),
                    message=err.get("message", "unknown"),
                    request_url=layer_url,
                )
            features = resp.get("features", [])
            if not features:
                return
            for feat in features:
                attrs = feat.get("attributes", {}) or {}
                yield {
                    "_object_id": attrs.get("OBJECTID")
                    or attrs.get("objectid")
                    or attrs.get("FID"),
                    "attributes": attrs,
                    "geometry": feat.get("geometry"),
                }
                emitted += 1
                if max_features and emitted >= max_features:
                    return
            # ArcGIS sends `exceededTransferLimit: true` when more pages exist.
            if not resp.get("exceededTransferLimit", False):
                # Some servers omit the flag; check page-vs-count boundary.
                if len(features) < page:
                    return
            offset += len(features)
