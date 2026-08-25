"""Source registry."""
from .greenhouse import GreenhouseSource
from .lever import LeverSource
from .ashby import AshbySource
from .github_repo import GithubRepoSource
from .adzuna import AdzunaSource

REGISTRY = {
    "greenhouse": GreenhouseSource,
    "lever": LeverSource,
    "ashby": AshbySource,
    "github_repo": GithubRepoSource,
    "adzuna": AdzunaSource,
}
