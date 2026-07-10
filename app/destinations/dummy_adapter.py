# app/destinations/dummy_adapter.py
import time
import json
from typing import Dict, Any
from app.worker.errors import (
    UnsupportedContractVersion,
    UnsupportedTaskType,
    InvalidTaskPayload,
    InvalidAgentResponse
)

class DummyAdapter:
    """A dummy task adapter for testing and diagnostics.
    
    Implements the TaskAdapter protocol.
    """
    
    def validate_task(self, task: Dict[str, Any]) -> None:
        if task.get("schema_version") != "cvn.agent_task.v1":
            raise UnsupportedContractVersion(f"Unsupported schema version: {task.get('schema_version')}")
        
        # Check basic envelope structure
        if "task" not in task or "instructions" not in task["task"]:
            raise InvalidTaskPayload("Missing task instructions in payload")
            
    def convert_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        instructions = task["task"]["instructions"]
        # Try to parse instructions as JSON to check if it's a structured test task
        try:
            inst_data = json.loads(instructions)
            if not isinstance(inst_data, dict):
                inst_data = {}
        except Exception:
            inst_data = {}
        return inst_data
        
    def execute(self, request: Dict[str, Any], timeout_seconds: int) -> Dict[str, Any]:
        task_type = request.get("task_type")
        if task_type == "cvn.test":
            test_mode = request.get("payload", {}).get("test_mode", "success")
            
            if test_mode == "success":
                time.sleep(1.0)
                return {"result": "success", "text": "CVN dummy processing successful."}
            elif test_mode == "fail_always":
                raise InvalidAgentResponse("Simulated permanent retryable failure in dummy execution")
            elif test_mode == "delay":
                time.sleep(min(timeout_seconds + 1.0, 5.0))
                return {"result": "success", "text": "CVN dummy delayed processing successful."}
            elif test_mode == "crash_after_claim":
                return {"result": "crash", "text": "Simulating worker crash."}
            else:
                raise UnsupportedTaskType(f"Unsupported test mode: {test_mode}")
        else:
            time.sleep(1.0)
            return {"result": "success", "text": "Simulated note processing summary."}
            
    def validate_response(self, response: Dict[str, Any]) -> Dict[str, Any]:
        if response.get("result") == "crash":
            import sys
            sys.exit(0)
        if "text" not in response:
            raise InvalidAgentResponse("Missing text in agent response")
        return {"result_summary": response["text"]}
