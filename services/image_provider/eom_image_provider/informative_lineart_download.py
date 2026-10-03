"""Public pinned model-source HTTP adapter; not called by the offline image worker."""

from __future__ import annotations

from http.client import HTTPException
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from eom_image_contracts import InformativeLineartUpstream

from eom_image_provider.provider import ProviderError


def fetch_informative_lineart_member(name: str, maximum_bytes: int) -> bytes:
    """No auth, arbitrary URL, mutable revision or executable remote Python input."""
    upstream = InformativeLineartUpstream.pinned()
    limits = {
        "README.md": 64 * 1024,
        "app.py": 64 * 1024,
        upstream.weight_filename: upstream.weight_bytes,
    }
    if name not in limits or maximum_bytes != limits[name]:
        raise ProviderError("LINEART_EXTRACTOR_DOWNLOAD_INVALID")
    url = f"{upstream.source_url}/resolve/{upstream.revision}/{name}"
    try:
        with urlopen(
            Request(url, headers={"User-Agent": "EOM-model-acquisition/1.0"}), timeout=30
        ) as response:
            # The public Hub may redirect weights to its HTTPS object store. No credentials
            # are supplied or forwarded. Reject downgrade even when the final bytes are pinned.
            if urlsplit(response.geturl()).scheme != "https":
                raise ProviderError("LINEART_EXTRACTOR_DOWNLOAD_INVALID")
            declared = response.headers.get("Content-Length")
            if declared is not None and not 0 < int(declared) <= maximum_bytes:
                raise ProviderError("LINEART_EXTRACTOR_DOWNLOAD_INVALID")
            payload = response.read(maximum_bytes + 1)
            if not 0 < len(payload) <= maximum_bytes:
                raise ProviderError("LINEART_EXTRACTOR_DOWNLOAD_INVALID")
            return bytes(payload)
    except ProviderError:
        raise
    except (OSError, URLError, ValueError, HTTPException) as exc:
        raise ProviderError("LINEART_EXTRACTOR_DOWNLOAD_FAILED") from exc
