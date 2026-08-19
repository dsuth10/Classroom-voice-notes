import json
import re
import time
from datetime import datetime
from enum import Enum
from typing import Any, Dict

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.audit.audit_logger import log_audit_event
from app.config.settings import is_loopback_url


class _ValueEnum(str, Enum):
    pass


class Route(_ValueEnum):
    LOCAL_OBSIDIAN = "local_obsidian"
    LOCAL_STUDENT_NOTE = "local_student_note"
    LOCAL_REMINDER = "local_reminder"
    TELEGRAM_AGENT_TASK = "telegram_agent_task"
    EMAIL_DRAFT = "email_draft"
    REVIEW_QUEUE = "review_queue"
    DISCARD_CANCELLED = "discard_cancelled"


class Sensitivity(_ValueEnum):
    STUDENT_SENSITIVE = "student_sensitive"
    TEACHER_PRIVATE = "teacher_private"
    NON_SENSITIVE = "non_sensitive"
    SCHOOL_SENSITIVE = "school_sensitive"
    UNKNOWN = "unknown"


class Category(_ValueEnum):
    STUDENT_NOTE = "student_note"
    BEHAVIOUR_NOTE = "behaviour_note"
    MATHS_NOTE = "maths_note"
    ENGLISH_NOTE = "english_note"
    SCIENCE_NOTE = "science_note"
    HASS_NOTE = "hass_note"
    DIGITECH_NOTE = "digitech_note"
    DESIGNTECH_NOTE = "designtech_note"
    REMINDER = "reminder"
    EMAIL_DRAFT = "email_draft"
    AGENT_TASK = "agent_task"
    GENERAL_NOTE = "general_note"
    UNKNOWN = "unknown"


class AgentTarget(_ValueEnum):
    HERMES = "hermes"
    OPENCLAW = "openclaw"
    AUTO = "auto"


class Priority(_ValueEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"


class TaskResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = "Agent task"
    instructions: str = ""
    priority: Priority = Priority.NORMAL

    @field_validator("priority", mode="before")
    @classmethod
    def normalise_priority(cls, value: Any) -> Any:
        return value.lower() if isinstance(value, str) else value


class CategoryFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    students_mentioned: list[str] = Field(default_factory=list)
    strand: str | None = None
    misconception_type: str | None = None
    behaviour_type: str | None = None
    action_taken: str | None = None
    observation_type: str | None = None
    year_level: str | None = None
    investigation_type: str | None = None
    text_type: str | None = None
    recipient: str | None = None
    subject_line: str | None = None
    priority: Priority | None = None

    @field_validator("priority", mode="before")
    @classmethod
    def normalise_priority(cls, value: Any) -> Any:
        return value.lower() if isinstance(value, str) else value


class ClassificationResult(BaseModel):
    """Validated response contract sent directly to Ollama as its JSON schema."""

    model_config = ConfigDict(extra="forbid")

    route: Route = Route.LOCAL_OBSIDIAN
    sensitivity: Sensitivity = Sensitivity.UNKNOWN
    category: Category = Category.GENERAL_NOTE
    title: str = "Voice Note"
    summary: str = ""
    contains_student_information: bool | None = None
    contains_external_task: bool = False
    telegram_allowed: bool = False
    requires_review: bool = False
    recommended_destination: str = ""
    reminder_time: str | None = None
    tags: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    agent_target: AgentTarget | None = None
    task: TaskResult | None = None
    category_fields: CategoryFields = Field(default_factory=CategoryFields)


class OllamaClassifier:
    def __init__(
        self,
        url: str = "http://localhost:11434",
        model: str = "qwen3.5:latest",
        fallback_model: str | None = "phi4-mini:3.8b",
        total_budget_seconds: float = 18.0,
    ) -> None:
        if not is_loopback_url(url):
            log_audit_event(
                "SECURITY_ERROR",
                "classifier",
                f"Attempted to configure non-loopback Ollama URL: {url}",
            )
            raise ValueError(
                "Ollama URL must point to local loopback "
                f"(localhost, 127.0.0.1, ::1). Got: {url}"
            )
        self.url = url
        self.model = model
        self.fallback_model = fallback_model
        self.total_budget_seconds = min(max(float(total_budget_seconds), 1.0), 120.0)

    def classify(
        self,
        transcript: str,
        recorded_at: str = "",
        duration_seconds: int = 0,
    ) -> Dict[str, Any]:
        """Classify once per model under one deadline, then fail closed."""
        if not is_loopback_url(self.url):
            log_audit_event(
                "SECURITY_ERROR",
                "classifier",
                f"Refusing classification with non-loopback Ollama URL: {self.url}",
            )
            raise ValueError(
                "Ollama URL must point to local loopback "
                f"(localhost, 127.0.0.1, ::1). Got: {self.url}"
            )

        started = time.monotonic()
        deadline = started + self.total_budget_seconds
        models = [self.model]
        if self.fallback_model and self.fallback_model != self.model:
            models.append(self.fallback_model)

        log_audit_event(
            "CLASSIFICATION_START",
            "session",
            f"models={models}; total_budget_seconds={self.total_budget_seconds:.3f}",
        )

        prompt = self._build_prompt(transcript, recorded_at, duration_seconds)
        schema = self._ollama_schema()
        last_valid: ClassificationResult | None = None

        for attempt_index, model in enumerate(models):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break

            # Reserve one quarter of the total budget for the smaller fallback.
            # The primary needs enough room for a cold local model load while
            # still staying below the 15-second p95 target on an 18-second budget.
            request_timeout = remaining
            if attempt_index == 0 and len(models) > 1:
                request_timeout = min(remaining, max(1.0, self.total_budget_seconds * 0.75))

            attempt_started = time.monotonic()
            try:
                result = self._classify_with_model(
                    model=model,
                    prompt=prompt,
                    schema=schema,
                    timeout_seconds=request_timeout,
                )
                result = self._normalise_result(result, transcript)
                last_valid = result
                uncertain = self._privacy_uncertain(result)
                elapsed = time.monotonic() - attempt_started
                log_audit_event(
                    "CLASSIFICATION_ATTEMPT",
                    "session",
                    f"model={model}; outcome={'uncertain' if uncertain else 'success'}; "
                    f"elapsed_seconds={elapsed:.3f}",
                )
                if not uncertain:
                    return self._success(result, model, started)
            except (httpx.HTTPError, RuntimeError, ValueError, ValidationError, json.JSONDecodeError) as exc:
                elapsed = time.monotonic() - attempt_started
                log_audit_event(
                    "CLASSIFICATION_ATTEMPT",
                    "session",
                    f"model={model}; outcome=error; elapsed_seconds={elapsed:.3f}; "
                    f"error_type={type(exc).__name__}",
                )
            except Exception as exc:
                # A local API response must never escape validation due to an
                # unexpected parsing failure.
                elapsed = time.monotonic() - attempt_started
                log_audit_event(
                    "CLASSIFICATION_ATTEMPT",
                    "session",
                    f"model={model}; outcome=error; elapsed_seconds={elapsed:.3f}; "
                    f"error_type={type(exc).__name__}",
                )

        if last_valid is not None:
            closed = self._fail_closed(last_valid)
            return self._success(closed, "fail_closed", started)

        total_elapsed = time.monotonic() - started
        log_audit_event(
            "CLASSIFICATION_ERROR",
            "session",
            f"All bounded attempts failed; elapsed_seconds={total_elapsed:.3f}",
        )
        return self._failure_result()

    def _classify_with_model(
        self,
        model: str,
        prompt: str,
        schema: Dict[str, Any],
        timeout_seconds: float,
    ) -> ClassificationResult:
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "format": schema,
            "think": False,
            "keep_alive": "10m",
            "options": {
                "temperature": 0,
                "num_ctx": 4096,
                "num_predict": 512,
            },
        }
        response = httpx.post(
            f"{self.url}/api/generate",
            json=payload,
            timeout=timeout_seconds,
        )
        if response.status_code != 200:
            raise RuntimeError(f"Ollama server returned status code: {response.status_code}")

        data = response.json()
        raw_text = str(data.get("response") or "").strip()
        if not raw_text:
            raise ValueError("Ollama response did not contain structured output")
        return ClassificationResult.model_validate_json(raw_text)

    @staticmethod
    def _ollama_schema() -> Dict[str, Any]:
        """Return a strict generation schema without output-biasing defaults.

        Pydantic defaults remain useful when normalising older test fixtures, but
        exposing those defaults to a small local model encourages it to copy an
        effectively empty classification. Ollama instead receives a schema in
        which every object property is required and additional fields are
        forbidden by the underlying Pydantic models.
        """
        schema = ClassificationResult.model_json_schema()

        def tighten(node: Any) -> None:
            if isinstance(node, dict):
                node.pop("default", None)
                properties = node.get("properties")
                if isinstance(properties, dict):
                    node["required"] = list(properties)
                for value in node.values():
                    tighten(value)
            elif isinstance(node, list):
                for value in node:
                    tighten(value)

        tighten(schema)
        return schema

    def _normalise_result(
        self,
        result: ClassificationResult,
        transcript: str,
    ) -> ClassificationResult:
        self._normalise_email_intent(result, transcript)
        self._normalise_cohort_note(result, transcript)

        if result.category == Category.REMINDER and result.reminder_time:
            try:
                parsed_reminder = datetime.fromisoformat(
                    result.reminder_time.replace("Z", "+00:00")
                )
                result.reminder_time = parsed_reminder.strftime("%Y-%m-%d %H:%M:%S")
            except ValueError:
                # Keep the model value for downstream review if it is not ISO-like.
                pass

        if result.category == Category.AGENT_TASK:
            task = result.task or TaskResult(
                title=result.title or "Agent task",
                instructions=result.summary,
            )
            instructions = self._repair_explicit_email_action(
                transcript,
                result.category_fields.model_dump(mode="json"),
                task.instructions,
            )
            instructions = self._enforce_confirmation_semantics(transcript, instructions)
            result.task = TaskResult(
                title=(task.title or result.title or "Agent task").strip(),
                instructions=instructions,
                priority=task.priority,
            )
            if result.agent_target is None:
                result.agent_target = AgentTarget.AUTO
        else:
            result.task = None

        safe_external = (
            result.category == Category.AGENT_TASK
            and result.sensitivity == Sensitivity.NON_SENSITIVE
            and result.contains_student_information is False
            and result.confidence >= 0.75
            and not result.requires_review
        )
        result.telegram_allowed = safe_external
        return result

    @staticmethod
    def _privacy_uncertain(result: ClassificationResult) -> bool:
        if result.confidence < 0.75 or result.sensitivity == Sensitivity.UNKNOWN:
            return True
        if result.category == Category.AGENT_TASK and (
            result.sensitivity != Sensitivity.NON_SENSITIVE
            or result.contains_student_information is not False
        ):
            return True
        return False

    def _normalise_email_intent(
        self,
        result: ClassificationResult,
        transcript: str,
    ) -> None:
        """Preserve explicit email verbs and literals before safety decisions."""
        normalised = " ".join(str(transcript).split())
        do_not_send = bool(
            re.search(r"\bdo\s+not\s+send\b|\bdon't\s+send\b", normalised, re.I)
        )
        send_requested = bool(
            re.search(r"\bsend\s+(?:an?\s+)?email\b", normalised, re.I)
        ) and not do_not_send
        draft_requested = bool(
            re.search(r"\bdraft\b.*\bemail\b", normalised, re.I)
        ) and not send_requested

        fields = result.category_fields
        if draft_requested:
            draft_match = re.search(
                r"\bdraft\s+an?\s+email\s+to\s+(.+?)\s+with\s+subjects?\s+"
                r"(.+?)\s+and\s+(?:the\s+)?body\s+(.+?)"
                r"(?=\s+do\s+not\s+send\b|\s+don't\s+send\b|$)",
                normalised,
                re.I,
            )
            if draft_match:
                recipient, subject, body = (part.strip() for part in draft_match.groups())
                fields.recipient = recipient
                fields.subject_line = subject
                result.summary = (
                    f"Draft an email to {recipient} with subject {subject} and body {body}"
                )
            result.route = Route.EMAIL_DRAFT
            result.category = Category.EMAIL_DRAFT
            result.contains_external_task = False
            result.telegram_allowed = False
            result.requires_review = True
            result.agent_target = None
            result.task = None
            return

        if not send_requested:
            return

        instructions = self._repair_explicit_email_action(
            normalised,
            fields.model_dump(mode="json"),
            result.task.instructions if result.task else "",
        )
        recipient_match = re.search(
            r"\bemail\s+to\s+(.+?)\s+with\s+subjects?\s+",
            normalised,
            re.I,
        )
        subject_match = re.search(
            r"\bwith\s+subjects?\s+(.+?)\s+and\s+(?:the\s+)?body\s+",
            normalised,
            re.I,
        )
        if recipient_match:
            fields.recipient = recipient_match.group(1).strip()
        if subject_match:
            fields.subject_line = subject_match.group(1).strip()

        result.route = Route.TELEGRAM_AGENT_TASK
        result.category = Category.AGENT_TASK
        result.contains_external_task = True
        result.agent_target = (
            AgentTarget.OPENCLAW
            if re.search(r"\bopenclaw\b", normalised, re.I)
            else (result.agent_target or AgentTarget.AUTO)
        )
        result.task = TaskResult(
            title=(result.task.title if result.task else result.title or "Send email"),
            instructions=instructions,
            priority=(result.task.priority if result.task else Priority.NORMAL),
        )

        sensitive_signal = re.search(
            r"\b(student|child|pupil|parent|guardian|family|families|behaviou?r|"
            r"welfare|medical|absence|pickup|assessment|achievement|support|injury|"
            r"allerg(?:y|ic)|medication|year\s+\d+)\b",
            normalised,
            re.I,
        )
        if (
            not sensitive_signal
            and result.contains_student_information is not True
            and result.sensitivity in {Sensitivity.NON_SENSITIVE, Sensitivity.TEACHER_PRIVATE}
        ):
            result.contains_student_information = False
            result.sensitivity = Sensitivity.NON_SENSITIVE
            result.requires_review = False

    @staticmethod
    def _normalise_cohort_note(
        result: ClassificationResult,
        transcript: str,
    ) -> None:
        """Do not treat a year-level cohort alone as an identifiable student."""
        if result.category != Category.GENERAL_NOTE:
            return
        if not re.search(r"\byear\s+\d+\s+class\b", transcript, re.I):
            return
        mentioned = result.category_fields.students_mentioned
        if mentioned and not all(
            re.fullmatch(r"year\s+\d+\s+class", name.strip(), re.I)
            for name in mentioned
        ):
            return
        if re.search(
            r"\b(welfare|medical|absence|pickup|family|behaviou?r|assessment|"
            r"achievement|support|injury|allerg(?:y|ic)|medication)\b",
            transcript,
            re.I,
        ):
            return
        result.route = Route.LOCAL_OBSIDIAN
        result.sensitivity = Sensitivity.TEACHER_PRIVATE
        result.contains_student_information = False
        result.requires_review = False
        result.category_fields.students_mentioned = []

    @staticmethod
    def _fail_closed(result: ClassificationResult) -> ClassificationResult:
        result.route = Route.REVIEW_QUEUE
        result.sensitivity = Sensitivity.UNKNOWN
        result.telegram_allowed = False
        result.requires_review = True
        result.confidence = 0.0
        return result

    def _success(
        self,
        result: ClassificationResult,
        model: str,
        started: float,
    ) -> Dict[str, Any]:
        elapsed = time.monotonic() - started
        log_audit_event(
            "CLASSIFICATION_SUCCESS",
            "session",
            f"model={model}; category={result.category.value}; "
            f"sensitivity={result.sensitivity.value}; elapsed_seconds={elapsed:.3f}",
        )
        return result.model_dump(mode="json")

    @staticmethod
    def _failure_result() -> Dict[str, Any]:
        return ClassificationResult(
            category=Category.UNKNOWN,
            route=Route.REVIEW_QUEUE,
            sensitivity=Sensitivity.UNKNOWN,
            confidence=0.0,
            title="Unclassified Note",
            summary="Classification failed within the local time budget.",
            telegram_allowed=False,
            requires_review=True,
        ).model_dump(mode="json")

    @staticmethod
    def _build_prompt(transcript: str, recorded_at: str, duration_seconds: int) -> str:
        return f"""
You are a local routing classifier for a teacher voice-note application.
Classify the transcript using the supplied JSON schema. Do not add prose.

Hard rules:
- Student names, achievement, behaviour, welfare, absence, pickup, family,
  medical, emotional, support or assessment information must stay local.
- If student-sensitive information may be present, set sensitivity to unknown or
  student_sensitive, telegram_allowed to false, and requires_review to true.
- Research, planning, communication, automation, software, file, calendar and
  email work with no student-sensitive information may be an agent_task.
- "draft an email" is email_draft and requires review; "send an email" is an agent_task
  whose task instructions explicitly say to send it.
- For agent_task, produce a self-contained task object. Preserve exact recipients,
  subjects, bodies, dates, success criteria and the exact phrase CONFIRM ACTION
  when spoken. Never invent CONFIRM ACTION.
- Do not invent facts or send normal classroom notes externally.
- If uncertain, use review_queue, unknown sensitivity and requires_review true.

Routing rules:
- A request beginning with "remind me" is a local reminder: use category
  reminder, route local_reminder, contains_external_task false, telegram_allowed
  false, and resolve reminder_time as YYYY-MM-DD HH:MM:SS from Recorded at.
- A request to draft but not send an email is category email_draft, route
  email_draft, requires_review true and telegram_allowed false.
- A request to send an email is category agent_task only when the sender actually
  asks for sending; preserve its literal fields and confirmation separately.
- Ordinary classroom observations are local general notes. Observations about an
  identifiable student are local student notes and student_sensitive.
- A year-level cohort such as "the Year 6 class" is not an identifiable student;
  keep a cohort-only classroom note teacher_private unless individual details are
  present.

Sensitivity and review rules:
- Use teacher_private, not unknown, for an ordinary local note or reminder that
  contains no student information. Such a local item does not require review.
- Use non_sensitive for a generic external task containing no student, contact,
  credential, path or school-sensitive information.
- Use student_sensitive whenever student information is present. Reserve unknown
  for genuine ambiguity; do not mark every teacher request unknown by default.

Agent target guidance:
- hermes: explicitly named Hermes, or general planning/research/instruction.
- openclaw: explicitly named OpenClaw, software, data or analytical processing.
- auto: agent task with no explicitly named agent.
- null: not an agent task.

Context:
- Recorded at: {recorded_at}
- Duration: {duration_seconds} seconds

Transcript: {json.dumps(transcript, ensure_ascii=False)}
""".strip()

    @staticmethod
    def _enforce_confirmation_semantics(transcript: str, instructions: str) -> str:
        spoken = bool(re.search(r"\bCONFIRM\s+ACTION\b", transcript, flags=re.IGNORECASE))
        cleaned = re.sub(
            r"(?:\s*\bCONFIRM\s+ACTION\b\s*)+",
            " ",
            instructions,
            flags=re.IGNORECASE,
        ).strip()
        if spoken:
            return f"{cleaned}\n\nCONFIRM ACTION" if cleaned else "CONFIRM ACTION"
        return cleaned

    @staticmethod
    def _repair_explicit_email_action(
        transcript: str,
        category_fields: Any,
        model_instructions: str,
    ) -> str:
        """Reconstruct explicit send-email fields from the user's own words."""
        normalised = " ".join(str(transcript).split())
        if not re.search(r"\bsend\b.*\bemail\b", normalised, flags=re.IGNORECASE):
            return model_instructions

        fields = category_fields if isinstance(category_fields, dict) else {}
        recipient_match = re.search(
            r"\bemail\s+to\s+(.+?)\s+with\s+subjects?\s+",
            normalised,
            flags=re.IGNORECASE,
        )
        subject_match = re.search(
            r"\bwith\s+subjects?\s+(.+?)\s+and\s+(?:the\s+)?body\s+",
            normalised,
            flags=re.IGNORECASE,
        )
        body_match = re.search(
            r"\band\s+(?:the\s+)?body\s+(.+?)(?=\s+confirm\s+action\b|\s+save\b|$)",
            normalised,
            flags=re.IGNORECASE,
        )

        recipient = (
            recipient_match.group(1).strip()
            if recipient_match
            else str(fields.get("recipient") or "").strip()
        )
        subject = (
            subject_match.group(1).strip()
            if subject_match
            else str(fields.get("subject_line") or "").strip()
        )
        body = body_match.group(1).strip() if body_match else ""
        if not recipient or not subject or not body:
            return model_instructions

        recipient_kept = bool(
            re.search(
                rf"\bemail\s+to\s+{re.escape(recipient)}\b",
                model_instructions,
                flags=re.IGNORECASE,
            )
        )
        if recipient_kept and subject in model_instructions and body in model_instructions:
            return model_instructions

        return (
            f"Send an email to {recipient} with subject "
            f"{json.dumps(subject, ensure_ascii=False)} and body "
            f"{json.dumps(body, ensure_ascii=False)}"
        )
