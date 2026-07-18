# app/destinations/openclaw_adapter.py
import json
import requests
from typing import Dict, Any
from app.worker.errors import (
    UnsupportedContractVersion,
    UnsupportedTaskType,
    UnsupportedTargetAgent,
    InvalidTaskPayload,
    GatewayAuthenticationError,
    GatewayUnavailableError,
    GatewayRateLimitError,
    GatewayConfigurationError,
    GatewayResponseError,
    ExecutionTimeoutUnknown,
    InvalidAgentResponse
)

class OpenClawAdapter:
    """Task adapter for OpenClaw gateway integration.

    Implements the TaskAdapter protocol.
    """

    def __init__(self, config: Dict[str, Any], gateway_token: str):
        self.config = config
        self.gateway_token = gateway_token

    def validate_task(self, task: Dict[str, Any]) -> None:
        # 1. Validate envelope version
        if task.get("schema_version") != "cvn.agent_task.v1":
            raise UnsupportedContractVersion(f"Unsupported schema version: {task.get('schema_version')}")

        # 2. Confirm target agent is openclaw
        if task.get("target_agent") != "openclaw":
            raise UnsupportedTargetAgent(f"Unsupported target agent: {task.get('target_agent')}")

        # 3. Check basic envelope payload fields
        if "task" not in task or "instructions" not in task["task"]:
            raise InvalidTaskPayload("Missing task instructions in envelope")

        instructions = task["task"]["instructions"]
        title = task["task"].get("title", "")

        # 4. Check payload limits
        if len(instructions) > 5000:
            raise InvalidTaskPayload("Task instructions exceed 5000 characters limit")
        if len(title) > 200:
            raise InvalidTaskPayload("Task title exceeds 200 characters limit")

        # 5. Try parsing instructions as JSON to check task type
        try:
            inst_data = json.loads(instructions)
            task_type = inst_data.get("task_type")
        except Exception:
            # If not JSON, default to classroom_note.summary which is allowlisted
            task_type = "classroom_note.summary"

        # 6. Confirm task type is allowlisted
        allowlisted_types = ["cvn.test", "classroom_note.summary"]
        if task_type not in allowlisted_types:
            raise UnsupportedTaskType(f"Unsupported task type: {task_type}")

        # 7. For cvn.test, validate test mode
        if task_type == "cvn.test":
            try:
                inst_data = json.loads(instructions)
                payload = inst_data.get("payload", {})
                test_mode = payload.get("test_mode") or payload.get("mode")
                if not test_mode:
                    raise InvalidTaskPayload("cvn.test task missing test_mode in payload")
                allowed_modes = ["success", "fail_once", "fail_always", "delay", "crash_after_claim", "echo"]
                if test_mode not in allowed_modes:
                    raise UnsupportedTaskType(f"Unsupported test mode: {test_mode}")
            except json.JSONDecodeError:
                raise InvalidTaskPayload("cvn.test instructions must be valid JSON")

    def convert_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        instructions = task["task"]["instructions"]
        task_id = task["task_id"]

        try:
            inst_data = json.loads(instructions)
        except Exception:
            inst_data = {}

        task_type = inst_data.get("task_type", "classroom_note.summary")

        if task_type == "cvn.test":
            payload = inst_data.get("payload", {})
            prompt = payload.get("text") or "Return exactly: CVN adapter connection successful."
            max_tokens = 200
        else:
            # classroom_note.summary
            payload = inst_data.get("payload", {})
            prompt = payload.get("text") or instructions
            max_tokens = self.config.get("maximum_output_tokens", 2000)

        return {
            "model": f"openclaw/{self.config.get('agent_id', 'cvn-broker')}",
            "input": prompt,
            "user": f"cvn-task:{task_id}",
            "stream": False,
            "max_output_tokens": max_tokens
        }

    def execute(self, request: Dict[str, Any], timeout_seconds: int) -> Dict[str, Any]:
        gateway_url = self.config.get("gateway_url", "http://127.0.0.1:18789").rstrip("/")
        responses_path = self.config.get("responses_path", "/v1/responses").lstrip("/")
        url = f"{gateway_url}/{responses_path}"

        connect_timeout = self.config.get("connect_timeout_seconds", 10.0)

        headers = {
            "Authorization": f"Bearer {self.gateway_token}",
            "Content-Type": "application/json"
        }

        try:
            response = requests.post(
                url,
                json=request,
                headers=headers,
                timeout=(connect_timeout, float(timeout_seconds))
            )
        except requests.exceptions.ConnectTimeout as e:
            raise GatewayUnavailableError(f"Gateway connection timed out: {e}")
        except requests.exceptions.ReadTimeout as e:
            raise ExecutionTimeoutUnknown(f"Gateway read timed out after dispatch: {e}")
        except requests.exceptions.ConnectionError as e:
            raise GatewayUnavailableError(f"Gateway connection failed: {e}")
        except requests.exceptions.RequestException as e:
            raise GatewayResponseError(f"Gateway HTTP request failed: {e}", 500)

        if response.status_code in (401, 403):
            raise GatewayAuthenticationError(f"Gateway authentication failed: HTTP {response.status_code}")
        elif response.status_code in (404, 405):
            raise GatewayConfigurationError(f"Gateway configuration error (endpoint disabled): HTTP {response.status_code}")
        elif response.status_code == 429:
            raise GatewayRateLimitError(f"Gateway rate limit exceeded: HTTP {response.status_code}")
        elif response.status_code >= 500:
            raise GatewayResponseError(f"Gateway server error: HTTP {response.status_code}", response.status_code)
        elif response.status_code != 200:
            raise GatewayResponseError(f"Gateway returned status {response.status_code}", response.status_code)

        try:
            data = response.json()
            if not isinstance(data, dict):
                raise InvalidAgentResponse("Gateway response JSON is not a dictionary")
            return data
        except Exception as e:
            if isinstance(e, InvalidAgentResponse):
                raise
            raise InvalidAgentResponse(f"Failed to parse gateway response JSON: {e}")

    def validate_response(self, response: Dict[str, Any]) -> Dict[str, Any]:
        # 1. Extract response output text
        output_text = None
        if "output" in response:
            raw_output = response["output"]
            if isinstance(raw_output, str):
                output_text = raw_output
            elif isinstance(raw_output, list):
                texts = []
                for item in raw_output:
                    if isinstance(item, dict):
                        if item.get("type") == "message" and "content" in item:
                            content_blocks = item["content"]
                            if isinstance(content_blocks, list):
                                for block in content_blocks:
                                    if isinstance(block, dict) and block.get("type") == "output_text":
                                        texts.append(block.get("text", ""))
                            elif isinstance(content_blocks, str):
                                texts.append(content_blocks)
                        elif "text" in item:
                            texts.append(item["text"])
                    elif isinstance(item, str):
                        texts.append(item)
                if texts:
                    output_text = "\n".join(texts)
        elif "choices" in response and len(response["choices"]) > 0:
            choice = response["choices"][0]
            if "message" in choice:
                output_text = choice["message"].get("content")

        if output_text is None:
            raise InvalidAgentResponse("No valid text output found in agent response")

        # 2. Reject unexpected tool calls
        tool_calls = response.get("tool_calls")
        if not tool_calls and "choices" in response and len(response["choices"]) > 0:
            tool_calls = response["choices"][0].get("message", {}).get("tool_calls")

        if tool_calls:
            raise InvalidAgentResponse("Security block: Agent attempted to perform unexpected tool calls")

        # 3. Apply size limits
        max_chars = self.config.get("maximum_result_characters", 20000)
        if len(output_text) > max_chars:
            raise InvalidAgentResponse(f"Agent response exceeded limit of {max_chars} characters")

        return {"result_summary": output_text.strip()}
