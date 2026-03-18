"""
QA Brain - LLM-powered intelligence for the QA Bot.

Uses OpenRouter API (OpenAI-compatible) with Claude Haiku 4.5.
Handles chat queries, workflow decisions, and general QA reasoning.
"""

import json
import logging
import re
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import LLMConfig, get_config
from .circuit_breaker import get_circuit_breaker, CircuitOpenError
from .prompts import (
    CHAT_SYSTEM_PROMPT,
    WORKFLOW_SYSTEM_PROMPT,
    ISSUE_QUERY_PROMPT,
    SENSITIVE_TOPICS,
    HELP_RESPONSE,
    PROMPT_VERSION,
    MEETING_SUMMARY_PROMPT,
    MEETING_SUMMARY_CHUNK_PROMPT,
)


class Capability(Enum):
    """Defined capabilities the brain can handle."""
    ISSUE_QUERY = "issue_query"
    REPO_INFO = "repo_info"
    WORKFLOW_DECISION = "workflow_decision"
    HELP = "help"
    ESCALATE = "escalate"
    GENERAL = "general"
    UNKNOWN = "unknown"
    # Chat-based workflow capabilities
    ONBOARDING = "onboarding"
    OFFBOARDING = "offboarding"
    MEETING_JOIN = "meeting_join"
    INTERN_STATUS = "intern_status"
    WEEKLY_REPORT = "weekly_report"


@dataclass
class ChatResponse:
    """Structured response from chat query."""
    response: str
    confidence: float
    capability: Capability
    tokens_used: int = 0
    latency_ms: int = 0
    filters: Optional[dict] = None


@dataclass
class WorkflowResponse:
    """Structured response for workflow decisions."""
    action: str  # approve, reject, escalate, request_info
    confidence: float
    reasoning: str
    details: Optional[dict] = None
    tokens_used: int = 0
    latency_ms: int = 0


class QABrain:
    """
    LLM-powered brain for QA operations.

    Uses OpenRouter API with Claude Haiku 4.5 for:
    - Natural language query understanding
    - Workflow decision making
    - General QA reasoning

    Includes circuit breaker for resilience against API failures.
    """

    OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

    def __init__(
        self,
        api_key: str,
        model: str = None,
        repos: list[str] = None,
        logger: logging.Logger = None,
        config: LLMConfig = None,
    ):
        """
        Initialize the QA Brain.

        Args:
            api_key: OpenRouter API key
            model: Model identifier (default from config)
            repos: List of monitored repository names
            logger: Logger instance
            config: LLM configuration (uses global config if not provided)
        """
        # Load config
        self.config = config or get_config().llm
        self.api_key = api_key
        self.model = model or self.config.model
        self.repos = repos or []
        self.logger = logger or logging.getLogger("qa_brain")

        # Compile sensitive topic patterns with word boundaries
        self._sensitive_patterns = [
            re.compile(r"\b" + re.escape(topic) + r"\b", re.IGNORECASE)
            for topic in SENSITIVE_TOPICS
        ]

        # Set up requests session with retry logic
        self._session = requests.Session()
        retry_strategy = Retry(
            total=self.config.max_retries,
            backoff_factor=self.config.retry_backoff_factor,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["POST"],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self._session.mount("https://", adapter)

        # Initialize circuit breaker
        self._circuit_breaker = get_circuit_breaker(
            name="openrouter",
            failure_threshold=5,  # Open after 5 consecutive failures
            recovery_timeout=30,  # Try again after 30s
            logger=self.logger,
        )

        self.logger.info(
            f"QABrain initialized: model={self.model}, repos={len(self.repos)}, "
            f"prompt_version={PROMPT_VERSION}, timeout={self.config.timeout_seconds}s"
        )

    def chat_query(
        self,
        user_query: str,
        user_name: str = "Unknown",
        timeout: int = None,
        conversation_history: list = None,
    ) -> ChatResponse:
        """
        Process a chat query from Zoom.

        Args:
            user_query: The user's message
            user_name: Display name of the user
            timeout: Request timeout in seconds
            conversation_history: Optional list of previous messages for context
                                  Format: [{"role": "user", "content": "..."}, ...]

        Returns:
            ChatResponse with response text and metadata
        """
        timeout = timeout or self.config.timeout_seconds
        start_time = time.time()

        # Check circuit breaker first
        if not self._circuit_breaker.can_execute():
            self.logger.warning("Circuit breaker open - using fallback response")
            return ChatResponse(
                response="I'm temporarily having connection issues. Try: `summary`, `high priority`, or `help`",
                confidence=0.0,
                capability=Capability.UNKNOWN,
                latency_ms=int((time.time() - start_time) * 1000),
            )

        # Check for sensitive topics first - always escalate
        if self._contains_sensitive_topic(user_query):
            return ChatResponse(
                response="I'll need to hand this off to Chad for sensitive topics. "
                         "Use `escalate` or I can notify them directly.",
                confidence=1.0,
                capability=Capability.ESCALATE,
                latency_ms=int((time.time() - start_time) * 1000),
            )

        # Check for explicit help request
        if user_query.lower().strip() in ["help", "?", "commands"]:
            return ChatResponse(
                response=HELP_RESPONSE,
                confidence=1.0,
                capability=Capability.HELP,
                latency_ms=int((time.time() - start_time) * 1000),
            )

        # Build system prompt with repo list
        max_repos = self.config.max_repos_in_prompt
        repos_formatted = ", ".join(self.repos[:max_repos])
        if len(self.repos) > max_repos:
            repos_formatted += f" ... and {len(self.repos) - max_repos} more"

        system_prompt = CHAT_SYSTEM_PROMPT.format(
            repos=repos_formatted,
            user_name=user_name,
        )

        # First, classify the query intent
        # Include conversation history so LLM understands follow-up questions like "those issues"
        intent_prompt = ISSUE_QUERY_PROMPT.format(query=user_query)

        try:
            # Build messages with conversation history for context
            intent_messages = [{"role": "system", "content": system_prompt}]
            if conversation_history:
                intent_messages.extend(conversation_history)
                self.logger.info(f"Intent classification using {len(conversation_history)} history messages")
            intent_messages.append({"role": "user", "content": intent_prompt})

            intent_response = self._call_llm(
                messages=intent_messages,
                timeout=timeout,
            )

            # Parse the intent
            intent_data = self._parse_json_response(intent_response)

            if intent_data:
                intent = intent_data.get("intent", "general")
                filters = intent_data.get("filters", {})
                response_hint = intent_data.get("response_hint", "")

                capability = self._map_intent_to_capability(intent)

                # For issue queries and repo info, we need to fetch data
                # Return the parsed intent so app.py can fetch and format
                if capability in [Capability.ISSUE_QUERY, Capability.REPO_INFO]:
                    return ChatResponse(
                        response=response_hint,
                        confidence=0.9,
                        capability=capability,
                        filters=filters,
                        latency_ms=int((time.time() - start_time) * 1000),
                        tokens_used=intent_data.get("_tokens", 0),
                    )

                # For workflow and meeting capabilities, include person/meeting name in filters
                if capability in [Capability.ONBOARDING, Capability.OFFBOARDING,
                                  Capability.INTERN_STATUS, Capability.MEETING_JOIN,
                                  Capability.WEEKLY_REPORT]:
                    # Extract additional fields from intent response
                    person_name = intent_data.get("person_name")
                    meeting_name = intent_data.get("meeting_name")

                    # Merge into filters for consistent handling
                    extended_filters = dict(filters) if filters else {}
                    if person_name:
                        extended_filters["person_name"] = person_name
                    if meeting_name:
                        extended_filters["meeting_name"] = meeting_name

                    return ChatResponse(
                        response=response_hint,
                        confidence=0.9,
                        capability=capability,
                        filters=extended_filters,
                        latency_ms=int((time.time() - start_time) * 1000),
                        tokens_used=intent_data.get("_tokens", 0),
                    )

                # For general queries, get a direct response
                if capability == Capability.GENERAL:
                    # Build messages with optional conversation history
                    messages = [{"role": "system", "content": system_prompt}]

                    # Add conversation history for context (enables follow-up questions)
                    if conversation_history:
                        messages.extend(conversation_history)
                        self.logger.debug(f"Including {len(conversation_history)} history messages for context")

                    messages.append({"role": "user", "content": user_query})

                    general_response = self._call_llm(
                        messages=messages,
                        timeout=timeout,
                    )
                    return ChatResponse(
                        response=general_response,
                        confidence=0.8,
                        capability=Capability.GENERAL,
                        latency_ms=int((time.time() - start_time) * 1000),
                    )

                # Help or escalate
                if capability == Capability.HELP:
                    return ChatResponse(
                        response=HELP_RESPONSE,
                        confidence=1.0,
                        capability=Capability.HELP,
                        latency_ms=int((time.time() - start_time) * 1000),
                    )

                if capability == Capability.ESCALATE:
                    return ChatResponse(
                        response="I'll connect you with Chad. Use `escalate` to send a notification.",
                        confidence=1.0,
                        capability=Capability.ESCALATE,
                        latency_ms=int((time.time() - start_time) * 1000),
                    )

        except requests.Timeout:
            self._circuit_breaker.record_failure()
            self.logger.warning(f"LLM timeout after {timeout}s for query: {user_query[:50]}...")
            return ChatResponse(
                response="I'm having trouble processing that. Try: `summary`, `high priority`, or `issues in [repo]`",
                confidence=0.0,
                capability=Capability.UNKNOWN,
                latency_ms=int((time.time() - start_time) * 1000),
            )

        except CircuitOpenError:
            self.logger.warning("Circuit breaker blocked request")
            return ChatResponse(
                response="I'm temporarily having connection issues. Try: `summary`, `high priority`, or `help`",
                confidence=0.0,
                capability=Capability.UNKNOWN,
                latency_ms=int((time.time() - start_time) * 1000),
            )

        except Exception as e:
            self._circuit_breaker.record_failure()
            self.logger.error(f"LLM error: {e}", exc_info=True)
            return ChatResponse(
                response="Something went wrong. Try: `summary`, `high priority`, or `help`",
                confidence=0.0,
                capability=Capability.UNKNOWN,
                latency_ms=int((time.time() - start_time) * 1000),
            )

        # Fallback
        return ChatResponse(
            response="I'm not sure how to help with that. Type `help` for available commands.",
            confidence=0.0,
            capability=Capability.UNKNOWN,
            latency_ms=int((time.time() - start_time) * 1000),
        )

    # Model for voice conversion - Haiku 4.5 for speed with enhanced prompt for quality
    VOICE_CONVERSION_MODEL = "anthropic/claude-haiku-4.5"

    def generate_voice_response(
        self,
        data: str,
        user_query: str,
        timeout: int = None,
    ) -> str:
        """
        Generate conversational voice response from data.

        Takes formatted data (markdown, lists) and converts it to natural speech
        suitable for TTS output in meetings.

        NOTE: This method intentionally does NOT use conversation history.
        The data parameter already contains the correct response for the current
        query (context was used during intent classification). Adding history
        here would cause the LLM to respond about previous topics instead of
        the current data.

        Uses Opus 4.5 for quality conversational tone while maintaining
        natural speech patterns.

        Args:
            data: The raw response data (may contain markdown, lists, etc.)
            user_query: The original user question
            timeout: Request timeout in seconds

        Returns:
            Natural conversational text suitable for TTS
        """
        import os

        # Voice conversion needs longer timeout for quality
        timeout = timeout or max(self.config.timeout_seconds, 10)
        start_time = time.time()

        # Check circuit breaker
        if not self._circuit_breaker.can_execute():
            self.logger.warning("Circuit breaker open for voice response - using raw data")
            return data

        try:
            # Load voice guidelines from file (cached after first load)
            if not hasattr(self, '_voice_guidelines'):
                guidelines_path = os.path.join(
                    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                    "docs", "VOICE_GUIDELINES.md"
                )
                try:
                    with open(guidelines_path, 'r', encoding='utf-8') as f:
                        self._voice_guidelines = f.read()
                    self.logger.info(f"Loaded voice guidelines from {guidelines_path}")
                except FileNotFoundError:
                    self.logger.warning("Voice guidelines not found, using minimal prompt")
                    self._voice_guidelines = None

            # Build system prompt from guidelines + current query/data
            if self._voice_guidelines:
                system_prompt = f"""{self._voice_guidelines}

---

## Current Request

**User asked:** {user_query}

**Data to summarize (use ONLY these facts):**
{data}

Generate a conversational voice response following the guidelines above. Remember: 2-3 sentences max, no markdown, numbers as words."""
            else:
                # Fallback minimal prompt
                system_prompt = f"""You are QA Bot speaking in a meeting. Be conversational and professional.
User asked: {user_query}
Data: {data}
Respond naturally in 2-3 sentences. No markdown. Numbers as words."""

            # Build messages - NO conversation history here!
            # The data already contains the correct response for this query.
            messages = [{"role": "system", "content": system_prompt}]
            messages.append({"role": "user", "content": "Generate the conversational voice response."})

            # Use Haiku 4.5 for voice conversion - fast with comprehensive guidelines
            voice_response = self._call_llm(messages, timeout=timeout, model_override=self.VOICE_CONVERSION_MODEL)

            latency = int((time.time() - start_time) * 1000)
            self.logger.info(f"Voice response generated in {latency}ms")

            return voice_response

        except Exception as e:
            self.logger.warning(f"Voice response generation failed: {e}, using raw data")
            return data

    def workflow_decision(
        self,
        trigger: str,
        data: dict,
        timeout: int = None,
    ) -> WorkflowResponse:
        """
        Make a workflow decision for n8n automation.

        Args:
            trigger: The workflow trigger type
            data: Context data for the decision
            timeout: Request timeout in seconds

        Returns:
            WorkflowResponse with action and reasoning
        """
        timeout = timeout or self.config.timeout_seconds
        start_time = time.time()

        # Check circuit breaker first
        if not self._circuit_breaker.can_execute():
            self.logger.warning("Circuit breaker open for workflow decision - escalating")
            return WorkflowResponse(
                action="escalate",
                confidence=0.0,
                reasoning="Service temporarily unavailable - escalating to human",
                latency_ms=int((time.time() - start_time) * 1000),
            )

        user_message = f"""Workflow trigger: {trigger}

Data:
{json.dumps(data, indent=2)}

What action should be taken?"""

        try:
            response = self._call_llm(
                messages=[
                    {"role": "system", "content": WORKFLOW_SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                timeout=timeout,
            )

            result = self._parse_json_response(response)

            if result:
                return WorkflowResponse(
                    action=result.get("action", "escalate"),
                    confidence=float(result.get("confidence", 0.5)),
                    reasoning=result.get("reasoning", "No reasoning provided"),
                    details=result.get("details"),
                    latency_ms=int((time.time() - start_time) * 1000),
                )

        except requests.Timeout:
            self.logger.warning(f"Workflow decision timeout for trigger: {trigger}")
        except Exception as e:
            self.logger.error(f"Workflow decision error: {e}", exc_info=True)

        # Default to escalate on any failure
        return WorkflowResponse(
            action="escalate",
            confidence=0.0,
            reasoning="Failed to process - escalating to human",
            latency_ms=int((time.time() - start_time) * 1000),
        )

    def generate_meeting_summary(
        self,
        transcript: str,
        meeting_name: str = "DevOps Meeting",
        meeting_date: str = None,
        duration: str = None,
        participants: list[str] = None,
        timeout: int = None,
    ) -> str:
        """
        Generate a summary of a meeting from its transcript.

        For long transcripts, uses chunking to process in parts then
        combines the extracted information.

        Args:
            transcript: Full meeting transcript
            meeting_name: Name of the meeting
            meeting_date: Date of the meeting (ISO format or human-readable)
            duration: Meeting duration
            participants: List of participant names
            timeout: Request timeout in seconds

        Returns:
            Formatted meeting summary suitable for Zoom Team Chat
        """
        timeout = timeout or self.config.timeout_seconds
        start_time = time.time()

        # Check circuit breaker
        if not self._circuit_breaker.can_execute():
            self.logger.warning("Circuit breaker open for meeting summary")
            return "Unable to generate meeting summary - service temporarily unavailable."

        # Default values
        if meeting_date is None:
            from datetime import datetime
            meeting_date = datetime.now().strftime("%B %d, %Y")

        participants_str = ", ".join(participants) if participants else "Not recorded"

        try:
            # Check transcript length (rough estimate: 4 chars per token)
            estimated_tokens = len(transcript) // 4
            max_input_tokens = 3000  # Leave room for prompt and response

            if estimated_tokens > max_input_tokens:
                # Use chunking approach for long transcripts
                return self._summarize_long_transcript(
                    transcript=transcript,
                    meeting_name=meeting_name,
                    meeting_date=meeting_date,
                    duration=duration,
                    participants_str=participants_str,
                    timeout=timeout,
                )

            # Short transcript - summarize directly
            prompt = MEETING_SUMMARY_PROMPT.format(
                meeting_name=meeting_name,
                meeting_date=meeting_date,
                duration=duration or "Not recorded",
                participants=participants_str,
                transcript=transcript,
            )

            messages = [
                {"role": "system", "content": "You are a meeting summarization assistant."},
                {"role": "user", "content": prompt},
            ]

            summary = self._call_llm(messages, timeout=timeout)

            latency = int((time.time() - start_time) * 1000)
            self.logger.info(f"Meeting summary generated in {latency}ms")

            return summary

        except Exception as e:
            self.logger.error(f"Meeting summary error: {e}", exc_info=True)
            return f"Unable to generate meeting summary: {str(e)}"

    def _summarize_long_transcript(
        self,
        transcript: str,
        meeting_name: str,
        meeting_date: str,
        duration: str,
        participants_str: str,
        timeout: int,
    ) -> str:
        """
        Summarize a long transcript using chunking.

        Splits transcript into chunks, extracts key info from each,
        then combines into final summary.
        """
        # Split into chunks (roughly 3000 chars each, about 750 tokens)
        chunk_size = 3000
        chunks = []
        words = transcript.split()
        current_chunk = []
        current_length = 0

        for word in words:
            current_chunk.append(word)
            current_length += len(word) + 1
            if current_length >= chunk_size:
                chunks.append(" ".join(current_chunk))
                current_chunk = []
                current_length = 0

        if current_chunk:
            chunks.append(" ".join(current_chunk))

        self.logger.info(f"Processing transcript in {len(chunks)} chunks")

        # Extract key info from each chunk
        all_decisions = []
        all_action_items = []
        all_discussion_points = []
        all_blockers = []
        all_quotes = []

        for i, chunk in enumerate(chunks):
            try:
                prompt = MEETING_SUMMARY_CHUNK_PROMPT.format(chunk=chunk)
                messages = [
                    {"role": "system", "content": "Extract meeting information as JSON."},
                    {"role": "user", "content": prompt},
                ]

                response = self._call_llm(messages, timeout=timeout)
                chunk_data = self._parse_json_response(response)

                if chunk_data:
                    all_decisions.extend(chunk_data.get("decisions", []))
                    all_action_items.extend(chunk_data.get("action_items", []))
                    all_discussion_points.extend(chunk_data.get("discussion_points", []))
                    all_blockers.extend(chunk_data.get("blockers", []))
                    all_quotes.extend(chunk_data.get("notable_quotes", []))

            except Exception as e:
                self.logger.warning(f"Failed to process chunk {i+1}: {e}")
                continue

        # Combine into final summary
        combined_data = {
            "decisions": all_decisions,
            "action_items": all_action_items,
            "discussion_points": all_discussion_points,
            "blockers": all_blockers,
            "quotes": all_quotes,
        }

        # Generate final summary from combined data
        final_prompt = f"""Create a meeting summary from the extracted information below.

Meeting: {meeting_name}
Date: {meeting_date}
Duration: {duration or "Not recorded"}
Participants: {participants_str}

Extracted Information:
{json.dumps(combined_data, indent=2)}

Generate a well-formatted meeting summary with sections for Key Decisions, Action Items, Discussion Highlights, and Blockers (if any). Use markdown formatting."""

        messages = [
            {"role": "system", "content": "You are a meeting summarization assistant."},
            {"role": "user", "content": final_prompt},
        ]

        return self._call_llm(messages, timeout=timeout)

    def enhance_workflow_output(
        self,
        service_name: str,
        raw_data: dict,
        output_channel: str = "zoom",
        timeout: int = None,
    ) -> str:
        """
        Enhance workflow service output with LLM intelligence.

        Takes structured data from services (reports, hygiene checks, etc.)
        and generates contextually appropriate, well-formatted responses.

        Args:
            service_name: Which service generated the data (report, hygiene, feedback)
            raw_data: Structured data from the service
            output_channel: Target channel for formatting hints
            timeout: Request timeout

        Returns:
            Enhanced, formatted content suitable for the target channel
        """
        from .prompts import WORKFLOW_ENHANCEMENT_PROMPT

        timeout = timeout or self.config.timeout_seconds
        start_time = time.time()

        # Check circuit breaker
        if not self._circuit_breaker.can_execute():
            self.logger.warning("Circuit breaker open for workflow enhancement")
            return self._fallback_workflow_format(service_name, raw_data)

        try:
            prompt = WORKFLOW_ENHANCEMENT_PROMPT.format(
                service_name=service_name,
                data=json.dumps(raw_data, indent=2, default=str),
                channel=output_channel
            )

            messages = [
                {"role": "system", "content": "You are a QA report formatter. Generate clean, professional messages."},
                {"role": "user", "content": prompt},
            ]

            result = self._call_llm(messages, timeout=timeout)

            latency = int((time.time() - start_time) * 1000)
            self.logger.info(f"Workflow enhancement ({service_name}) completed in {latency}ms")

            return result

        except Exception as e:
            self.logger.warning(f"Workflow enhancement failed: {e}, using fallback")
            return self._fallback_workflow_format(service_name, raw_data)

    def _fallback_workflow_format(self, service_name: str, data: dict) -> str:
        """
        Fallback formatting when LLM unavailable.

        Uses simple template-based formatting.
        """
        from .prompts import (
            REPORT_FALLBACK_TEMPLATE,
            HYGIENE_FALLBACK_TEMPLATE,
            FEEDBACK_FALLBACK_TEMPLATE,
        )
        from datetime import datetime

        date_str = datetime.now().strftime("%B %d, %Y")

        if service_name == "report":
            # Format repo breakdown
            repo_breakdown = ""
            by_repo = data.get("by_repo", {})
            if by_repo:
                repo_breakdown = "By Repository:\n"
                for repo, count in sorted(by_repo.items(), key=lambda x: -x[1]):
                    repo_breakdown += f"  {repo}: {count}\n"

            return REPORT_FALLBACK_TEMPLATE.format(
                date=date_str,
                total=data.get("total_issues", 0),
                high_priority=data.get("high_priority", 0),
                unassigned=data.get("unassigned", 0),
                stale=data.get("stale", 0),
                repo_breakdown=repo_breakdown,
            )

        elif service_name == "hygiene":
            # Format issues breakdown
            breakdown_lines = []
            if data.get("missing_priority_count", 0) > 0:
                breakdown_lines.append(f"Missing Priority: {data['missing_priority_count']}")
            if data.get("missing_assignee_count", 0) > 0:
                breakdown_lines.append(f"Unassigned: {data['missing_assignee_count']}")
            if data.get("stale_issues_count", 0) > 0:
                breakdown_lines.append(f"Stale: {data['stale_issues_count']}")
            if data.get("missing_labels_count", 0) > 0:
                breakdown_lines.append(f"Missing Labels: {data['missing_labels_count']}")

            issues_breakdown = "\n".join(breakdown_lines) if breakdown_lines else "All issues are properly maintained!"

            return HYGIENE_FALLBACK_TEMPLATE.format(
                date=date_str,
                total_checked=data.get("total_issues_checked", 0),
                needs_attention=data.get("issues_needing_attention", 0),
                issues_breakdown=issues_breakdown,
            )

        elif service_name == "feedback":
            # Format intern list
            interns = data.get("interns", [])
            intern_lines = []
            for intern in interns:
                name = intern.get("name", "Unknown")
                program = intern.get("program", "")
                supervisor = intern.get("supervisor", "Unassigned")
                line = f"- {name}"
                if program:
                    line += f" ({program})"
                line += f" - Supervisor: {supervisor}"
                intern_lines.append(line)

            return FEEDBACK_FALLBACK_TEMPLATE.format(
                date=date_str,
                total_interns=len(interns),
                intern_list="\n".join(intern_lines) if intern_lines else "No active interns.",
            )

        # Generic fallback
        return json.dumps(data, indent=2, default=str)

    def _call_llm(
        self,
        messages: list[dict],
        timeout: int = None,
        model_override: str = None,
    ) -> str:
        """
        Make a call to OpenRouter API.

        Uses session with automatic retry for transient failures.
        Records success/failure for circuit breaker.

        Args:
            messages: Chat messages in OpenAI format
            timeout: Request timeout in seconds
            model_override: Use a different model (e.g., haiku for speed)

        Returns:
            Response text from the model
        """
        timeout = timeout or self.config.timeout_seconds
        model = model_override or self.model
        start_time = time.time()

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://cloudwarriors.ai",  # Required by OpenRouter
            "X-Title": "QA Bot",  # Optional, for OpenRouter dashboard
        }

        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": self.config.max_tokens,
            "temperature": self.config.temperature,
        }

        # Use session with retry logic
        response = self._session.post(
            self.OPENROUTER_URL,
            headers=headers,
            json=payload,
            timeout=timeout,
        )

        latency_ms = int((time.time() - start_time) * 1000)

        if response.status_code != 200:
            # Sanitize error response - don't log full response which might contain secrets
            error_msg = self._sanitize_error_response(response)
            self.logger.error(f"OpenRouter error: {response.status_code} - {error_msg}")
            response.raise_for_status()

        result = response.json()
        content = result["choices"][0]["message"]["content"]
        tokens = result.get("usage", {}).get("total_tokens", 0)

        # Record success for circuit breaker
        self._circuit_breaker.record_success()

        # Log sanitized version (no actual content, just metadata)
        self.logger.info(
            f"LLM call: model={model}, tokens={tokens}, latency={latency_ms}ms"
        )

        return content

    def get_health_status(self) -> dict:
        """
        Get health status for the LLM brain.

        Returns status information including circuit breaker state.
        """
        circuit_status = self._circuit_breaker.get_status()
        return {
            "status": "ok" if circuit_status["state"] == "closed" else "degraded",
            "model": self.model,
            "circuit_breaker": circuit_status,
            "config": {
                "timeout_seconds": self.config.timeout_seconds,
                "max_retries": self.config.max_retries,
                "max_tokens": self.config.max_tokens,
            }
        }

    def _sanitize_error_response(self, response: requests.Response) -> str:
        """
        Sanitize error response to avoid leaking secrets in logs.

        SECURITY: Uses centralized sanitization utilities for comprehensive
        secret redaction. Whitelist approach for JSON, pattern matching for text.
        """
        from .errors import sanitize_error_json, sanitize_response_text

        try:
            error_json = response.json()
            # Whitelist approach: only include explicitly safe fields
            sanitized = sanitize_error_json(error_json)
            if sanitized:
                return json.dumps(sanitized)
        except (json.JSONDecodeError, ValueError):
            pass

        # Fallback: use comprehensive pattern-based sanitization
        return sanitize_response_text(response.text)

    def _parse_json_response(self, text: str) -> Optional[dict]:
        """Parse JSON from LLM response, handling markdown code blocks."""
        # Remove markdown code blocks if present
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            # Remove first and last lines (``` markers)
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Try to find JSON in the response
            import re
            json_match = re.search(r'\{[^{}]*\}', text, re.DOTALL)
            if json_match:
                try:
                    return json.loads(json_match.group())
                except json.JSONDecodeError:
                    pass

            self.logger.warning(f"Failed to parse JSON from LLM response: {text[:100]}...")
            return None

    def _contains_sensitive_topic(self, text: str) -> bool:
        """Check if text contains sensitive topics requiring escalation.

        Uses word boundaries to avoid false positives (e.g., 'compensation'
        won't match 'decompensation').
        """
        return any(pattern.search(text) for pattern in self._sensitive_patterns)

    def _map_intent_to_capability(self, intent: str) -> Capability:
        """Map intent string to Capability enum."""
        mapping = {
            "issue_query": Capability.ISSUE_QUERY,
            "repo_info": Capability.REPO_INFO,
            "help": Capability.HELP,
            "escalate": Capability.ESCALATE,
            "general": Capability.GENERAL,
            # New chat-based workflow intents
            "onboarding": Capability.ONBOARDING,
            "offboarding": Capability.OFFBOARDING,
            "meeting_join": Capability.MEETING_JOIN,
            "intern_status": Capability.INTERN_STATUS,
            "weekly_report": Capability.WEEKLY_REPORT,
        }
        return mapping.get(intent, Capability.UNKNOWN)
