"""Base class every source adapter implements. One shape in, Jobs out."""
from __future__ import annotations

from abc import ABC, abstractmethod

import requests

from ..models import Job

USER_AGENT = "jobhunt/1.0 (personal job search tool)"


class Source(ABC):
    name: str = "base"

    def __init__(self, config: dict, secrets: dict):
        self.config = config
        self.secrets = secrets
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})

    @abstractmethod
    def fetch(self) -> list[Job]:
        """Return raw (un-deduped, un-filtered) jobs from this source."""
        ...

    def _get(self, url: str, **kwargs):
        kwargs.setdefault("timeout", 20)
        return self.session.get(url, **kwargs)
