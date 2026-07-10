# app/destinations/base_adapter.py
from typing import Protocol, Dict, Any

class TaskAdapter(Protocol):
    """Protocol defining the interface for all external task adapters."""
    
    def validate_task(self, task: Dict[str, Any]) -> None:
        """Validates the task envelope and instructions payload.
        
        Raises typed exceptions if validation fails.
        """
        ...
        
    def convert_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """Converts the task payload into the format expected by the target agent."""
        ...
        
    def execute(self, request: Dict[str, Any], timeout_seconds: int) -> Dict[str, Any]:
        """Sends the request to the agent and returns the raw response."""
        ...
        
    def validate_response(self, response: Dict[str, Any]) -> Dict[str, Any]:
        """Validates and sanitises the agent response.
        
        Raises typed exceptions if response is invalid or unsafe.
        """
        ...
