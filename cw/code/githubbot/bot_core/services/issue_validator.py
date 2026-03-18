"""Issue validator service with LLM-powered validation"""
import asyncio
import logging
import os
from typing import Tuple, Optional
from asgiref.sync import sync_to_async

logger = logging.getLogger(__name__)


class IssueValidatorService:
    """
    Service for validating issue quality with LLM.

    Coordinates:
    - Screenshot URL validation (SSRF protection)
    - Circuit breaker (resilience)
    - Rate limiting (cost control)
    - LLM validation (quality scoring)
    """

    # Validation score thresholds
    PASS_THRESHOLD = int(os.getenv('VALIDATION_SCORE_EXCELLENT', '70'))
    NEEDS_WORK_THRESHOLD = int(os.getenv('VALIDATION_SCORE_NEEDS_WORK', '40'))
    MAX_VALIDATION_ATTEMPTS = int(os.getenv('MAX_VALIDATION_ATTEMPTS', '3'))

    def __init__(self):
        """Initialize validator with dependencies"""
        from bot_core.services.circuit_breaker import validation_circuit_breaker
        from bot_core.services.rate_limiter import rate_limiter
        from bot_core.services.screenshot_validator import validate_screenshot_urls

        self.circuit_breaker = validation_circuit_breaker
        self.rate_limiter = rate_limiter
        self.validate_screenshot_urls = validate_screenshot_urls

    async def validate_issue(
        self,
        conversation
    ) -> Tuple[bool, Optional[object], Optional[str]]:
        """
        Validate issue with GPT-4 Vision.

        Args:
            conversation: IssueConversation model instance

        Returns:
            Tuple of (should_create, validation_result, error_message)
            - should_create: True if issue should be created
            - validation_result: IssueValidationResult or None
            - error_message: Error message or None
        """
        from bot_core.llm_bot import IssueValidationResult

        # Check circuit breaker
        if not self.circuit_breaker.should_attempt():
            logger.warning("Circuit breaker open - skipping validation")
            return True, None, "⚠️ Validation service temporarily unavailable. Creating issue without validation."

        # Check attempt limit
        if conversation.validation_attempts >= self.MAX_VALIDATION_ATTEMPTS:
            logger.warning(f"Max validation attempts reached for conversation {conversation.id}")
            return False, None, f"❌ Maximum validation attempts ({self.MAX_VALIDATION_ATTEMPTS}) reached. Please contact support."

        # Check rate limits
        user_allowed, user_error = self.rate_limiter.check_user_limit(conversation.user_jid)
        if not user_allowed:
            return False, None, user_error

        # Check daily budget
        budget_allowed, budget_error = self.rate_limiter.check_daily_budget()
        if not budget_allowed:
            logger.warning("Daily validation budget exceeded")
            return True, None, budget_error

        # Validate screenshot URLs (SSRF protection)
        if conversation.screenshot_urls:
            urls_valid, url_error = await self.validate_screenshot_urls(conversation.screenshot_urls)
            if not urls_valid:
                logger.warning(f"Screenshot URL validation failed: {url_error}")
                return False, None, f"❌ {url_error}"

        try:
            # Call LLM validation with timeout
            result = await asyncio.wait_for(
                self._call_llm_validation(conversation),
                timeout=float(os.getenv('OPENAI_VALIDATION_TIMEOUT', '15'))
            )

            # Record success
            self.circuit_breaker.record_success()

            # Record cost (estimated $0.06 per validation)
            estimated_cost = 0.06
            if conversation.screenshot_urls:
                estimated_cost += len(conversation.screenshot_urls) * 0.019
            self.rate_limiter.record_validation_cost(estimated_cost)

            # Determine verdict based on score
            if result.score >= self.PASS_THRESHOLD:
                result.severity = "pass"
                should_create = True
            elif result.score >= self.NEEDS_WORK_THRESHOLD:
                result.severity = "needs_improvement"
                should_create = False
            else:
                result.severity = "insufficient"
                should_create = False

            # Update conversation
            def _update():
                conversation.validation_attempts += 1
                conversation.validation_score = result.score
                conversation.validation_feedback = result.model_dump()
                conversation.save()

            await sync_to_async(_update)()

            logger.info(
                f"Validation complete for conversation {conversation.id}: "
                f"score={result.score}, severity={result.severity}, should_create={should_create}"
            )

            return should_create, result, None

        except asyncio.TimeoutError:
            logger.error("Validation timeout")
            self.circuit_breaker.record_failure()
            return True, None, "⚠️ Validation timeout - creating issue without validation."

        except Exception as e:
            logger.error(f"Validation error: {e}", exc_info=True)
            self.circuit_breaker.record_failure()
            return True, None, f"⚠️ Validation error - creating issue without validation."

    async def _call_llm_validation(self, conversation):
        """Call LLM with vision to validate issue"""
        from bot_core.llm_bot import llm_bot

        result = await llm_bot.validate_issue_with_vision(
            title=conversation.issue_title,
            description=conversation.description,
            screenshot_urls=conversation.screenshot_urls or [],
            reproduction_steps=conversation.reproduction_steps,
            environment=conversation.environment,
            expected_behavior=conversation.expected_behavior,
            actual_behavior=conversation.actual_behavior,
            application_name=conversation.selected_app.name if conversation.selected_app else "Unknown"
        )

        return result


# Singleton instance
issue_validator = IssueValidatorService()
