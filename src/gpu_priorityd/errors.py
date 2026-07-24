class GPUPriorityError(RuntimeError):
    """Base error for expected policy and runtime failures."""


class ConfigurationError(GPUPriorityError):
    """The configuration is invalid or incomplete."""


class AdmissionBlocked(GPUPriorityError):
    """A priority service cannot safely claim the GPU."""


class PlatformUnavailable(GPUPriorityError):
    """The requested production backend is unavailable on this host."""

