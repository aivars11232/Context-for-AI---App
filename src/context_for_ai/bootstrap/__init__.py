"""Composition boundary contracts; concrete assembly remains later-task work."""

from context_for_ai.bootstrap.contracts import (
    ApplicationDependencies,
    ApplicationUseCases,
    CompositionRoot,
    DeterministicComponents,
    RepositoryPorts,
    SystemPorts,
)
from context_for_ai.bootstrap.shell_composition import (
    ProductionShellScopeFactory,
    UtcSystemClock,
    UuidDomainIdGenerator,
    UuidIdempotencyKeyFactory,
    configuration_snapshot_from,
)


__all__ = [
    "ApplicationDependencies",
    "ApplicationUseCases",
    "CompositionRoot",
    "DeterministicComponents",
    "ProductionShellScopeFactory",
    "RepositoryPorts",
    "SystemPorts",
    "UtcSystemClock",
    "UuidDomainIdGenerator",
    "UuidIdempotencyKeyFactory",
    "configuration_snapshot_from",
]
