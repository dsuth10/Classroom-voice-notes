# app/worker/errors.py

class WorkerError(Exception):
    """Base exception for all worker errors."""
    pass

class UnsupportedContractVersion(WorkerError):
    """Raised when the task payload version is unsupported."""
    pass

class UnsupportedTaskType(WorkerError):
    """Raised when the task type is not allowlisted."""
    pass

class UnsupportedTargetAgent(WorkerError):
    """Raised when the logical agent target is not supported."""
    pass

class InvalidTaskPayload(WorkerError):
    """Raised when the task envelope or payload is structurally invalid."""
    pass

class GatewayAuthenticationError(WorkerError):
    """Raised when authentication with the gateway fails."""
    pass

class GatewayUnavailableError(WorkerError):
    """Raised when the gateway is unreachable."""
    pass

class GatewayRateLimitError(WorkerError):
    """Raised when the gateway rate-limits the worker."""
    pass

class GatewayConfigurationError(WorkerError):
    """Raised when the gateway configuration is invalid or endpoint disabled."""
    pass

class GatewayResponseError(WorkerError):
    """Raised when the gateway returns a non-200 HTTP response."""
    def __init__(self, message: str, status_code: int):
        super().__init__(message)
        self.status_code = status_code

class ExecutionTimeoutUnknown(WorkerError):
    """Raised when a read timeout occurs, meaning execution state is unknown."""
    pass

class InvalidAgentResponse(WorkerError):
    """Raised when the agent returns an invalid or unsafe response."""
    pass
