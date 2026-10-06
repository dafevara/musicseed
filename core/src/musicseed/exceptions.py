"""MusicSeed domain exceptions."""


class MusicSeedError(Exception):
    """Base exception for all MusicSeed errors."""


class ConfigurationError(MusicSeedError):
    """Required configuration is missing or invalid."""


class NotFoundError(MusicSeedError):
    """A requested resource (seed track, file, playlist) could not be found."""


class JobConflictError(MusicSeedError):
    """A job of the requested kind is already running."""


class CalculationCanceledError(MusicSeedError):
    """A recommendation calculation stopped at a cooperative checkpoint."""
