"""Cached, fault-tolerant HTTP fetching.

Files are accessed programmatically (never downloaded by hand) and cached on
disk. A file is only re-downloaded when it is missing or its size disagrees with
the server's ``Content-Length``, so re-running the pipeline is cheap and
idempotent. Each download is written atomically (to a temp file, then renamed)
so an interrupted run never leaves a half-written raster behind.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

_CHUNK = 1 << 20  # 1 MiB
_TIMEOUT = (10, 60)  # (connect, read) seconds
_MAX_ATTEMPTS = 6    # whole-download retries (covers mid-stream disconnects)


def make_session() -> requests.Session:
    """A session that transparently retries connection and 5xx errors with backoff.

    WorldPop and GADM are public mirrors that occasionally reset connections, so
    the Retry adapter reconnects and a single dropped socket never fails the run.
    """
    retry = Retry(
        total=5,
        connect=5,
        read=5,
        backoff_factor=1.5,                       # waits grow: 0, 1.5, 3, 6, 12s
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "HEAD"}),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session = requests.Session()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def _remote_size(url: str, session: requests.Session) -> int | None:
    """Best-effort Content-Length from a HEAD request; None if unknown."""
    try:
        r = session.head(url, allow_redirects=True, timeout=_TIMEOUT)
        r.raise_for_status()
        cl = r.headers.get("Content-Length")
        return int(cl) if cl is not None else None
    except (requests.RequestException, ValueError):
        return None


def fetch_file(
    url: str,
    dest: Path,
    session: requests.Session | None = None,
    *,
    force: bool = False,
) -> Path:
    """Download ``url`` to ``dest`` unless a valid cached copy already exists.

    Returns the local path. Validates size against the server when possible.
    """
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    owns_session = session is None
    session = session or make_session()
    try:
        if dest.exists() and not force:
            remote = _remote_size(url, session)
            if remote is None or dest.stat().st_size == remote:
                return dest  # cache hit

        tmp = dest.with_suffix(dest.suffix + ".part")
        last_err: Exception | None = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                with session.get(url, stream=True, timeout=_TIMEOUT) as r:
                    r.raise_for_status()
                    with open(tmp, "wb") as fh:
                        for chunk in r.iter_content(chunk_size=_CHUNK):
                            if chunk:
                                fh.write(chunk)
                os.replace(tmp, dest)  # atomic on same filesystem
                return dest
            except (requests.RequestException, OSError) as exc:
                # Mid-stream disconnect: discard the partial and back off.
                last_err = exc
                tmp.unlink(missing_ok=True)
                if attempt < _MAX_ATTEMPTS:
                    time.sleep(min(2 ** attempt, 30))
        raise RuntimeError(
            f"Failed to download {url} after {_MAX_ATTEMPTS} attempts"
        ) from last_err
    finally:
        if owns_session:
            session.close()


def fetch_many(
    urls_and_dests: list[tuple[str, Path]],
    *,
    force: bool = False,
    progress: bool = True,
    max_workers: int = 8,
) -> list[Path]:
    """Fetch many (url, dest) pairs concurrently.

    Downloads are I/O-bound, so a small thread pool dramatically cuts wall-clock
    over a high-latency link. Each worker uses its own retrying session; results
    are returned in the original input order.
    """
    import threading
    from concurrent.futures import ThreadPoolExecutor

    local = threading.local()

    def worker(item: tuple[int, tuple[str, Path]]):
        idx, (url, dest) = item
        if not hasattr(local, "session"):
            local.session = make_session()
        return idx, fetch_file(url, dest, session=local.session, force=force)

    workers = max(1, min(max_workers, len(urls_and_dests)))
    results: list[Path | None] = [None] * len(urls_and_dests)
    indexed = list(enumerate(urls_and_dests))

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = pool.map(worker, indexed)
        if progress:
            try:
                from tqdm import tqdm

                futures = tqdm(
                    futures, total=len(indexed), desc="Fetching rasters", unit="file"
                )
            except ImportError:  # progress bar is optional
                pass
        for idx, path in futures:
            results[idx] = path

    return [p for p in results if p is not None]
