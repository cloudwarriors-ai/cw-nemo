"""Celery tasks for async validation and cleanup"""
import logging
import asyncio
from datetime import timedelta
from django.utils import timezone
from celery import shared_task
from asgiref.sync import sync_to_async

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3)
def validate_and_notify_issue(self, conversation_id):
    """
    Validate issue with GPT-4 Vision and notify user.

    This runs asynchronously to avoid Zoom webhook timeout.

    Args:
        conversation_id: IssueConversation ID
    """
    from bot_core.models import IssueConversation, Application
    from bot_core.services.issue_validator import issue_validator
    from bot_core.issue_maker_bot import issue_maker_bot

    logger.info(f"Starting validation task for conversation {conversation_id}")

    try:
        # Get conversation
        try:
            conversation = IssueConversation.objects.select_related('selected_app').get(
                id=conversation_id
            )
        except IssueConversation.DoesNotExist:
            logger.warning(f"Conversation {conversation_id} not found (may have been deleted)")
            return

        # Validate app still exists
        if not conversation.selected_app or not conversation.selected_app.is_active:
            logger.error(f"App deleted or deactivated for conversation {conversation_id}")
            try:
                issue_maker_bot.send_message({
                    'head': {'text': 'Error'},
                    'body': [{
                        'type': 'message',
                        'text': '❌ The selected application is no longer available. Please create your issue again.'
                    }]
                }, conversation.channel_jid or conversation.user_jid)
            except Exception as e:
                logger.error(f"Failed to send error message: {e}")
            return

        # Run validation (async)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            should_create, result, error = loop.run_until_complete(
                issue_validator.validate_issue(conversation)
            )
        finally:
            loop.close()

        # Send result message
        if error:
            # Validation failed - send warning and create anyway
            _send_validation_warning(conversation, error)
            _create_github_issue(conversation)

        elif should_create and result:
            # Validation passed - create issue with score
            _create_github_issue(conversation, validation_result=result)

        elif result:
            # Validation failed - send feedback
            _send_validation_feedback(conversation, result)

        else:
            # Unexpected state
            logger.error(f"Unexpected validation state for conversation {conversation_id}")
            _send_validation_warning(conversation, "Unexpected validation error")

    except Exception as e:
        logger.error(f"Validation task failed for conversation {conversation_id}: {e}", exc_info=True)

        # Retry with exponential backoff
        try:
            self.retry(exc=e, countdown=2 ** self.request.retries)
        except self.MaxRetriesExceededError:
            logger.error(f"Max retries exceeded for conversation {conversation_id}")
            # Send error message to user
            try:
                from bot_core.models import IssueConversation
                conversation = IssueConversation.objects.get(id=conversation_id)
                _send_validation_warning(
                    conversation,
                    "Validation service is temporarily unavailable. Please try again later."
                )
            except Exception:
                pass


def _send_validation_warning(conversation, warning_message):
    """Send validation warning and create issue anyway"""
    from bot_core.issue_maker_bot import issue_maker_bot
    from bot_core.github_bot import github_bot

    try:
        issue_maker_bot.send_message({
            'head': {'text': 'Validation Warning'},
            'body': [{
                'type': 'message',
                'text': f'{warning_message}\n\n✅ Creating issue anyway...'
            }]
        }, conversation.channel_jid or conversation.user_jid)
    except Exception as e:
        logger.error(f"Failed to send warning message: {e}")


def _send_validation_feedback(conversation, validation_result):
    """Send validation feedback to user"""
    from bot_core.issue_maker_bot import issue_maker_bot

    severity_emoji = {
        "insufficient": "❌",
        "needs_improvement": "⚠️",
        "pass": "✅"
    }

    severity_title = {
        "insufficient": "Cannot Create Issue - Insufficient Information",
        "needs_improvement": "Issue Needs Improvement",
        "pass": "Issue Looks Great!"
    }

    emoji = severity_emoji.get(validation_result.severity, "⚠️")
    title = severity_title.get(validation_result.severity, "Validation Result")

    # Build feedback message
    score_text = f"""**Quality Score: {validation_result.score}/100**
• Clarity: {validation_result.clarity_score}/10
• Completeness: {validation_result.completeness_score}/10
• Actionability: {validation_result.actionability_score}/10
• Screenshot Quality: {validation_result.screenshot_score}/10
• Reproducibility: {validation_result.reproducibility_score}/10"""

    body_parts = [{'type': 'message', 'text': f"{emoji} **{title}**\n\n{score_text}"}]

    # Add missing info
    if validation_result.missing_info:
        missing_text = "**Missing Information:**\n" + "\n".join(
            f"• {item}" for item in validation_result.missing_info
        )
        body_parts.append({'type': 'message', 'text': missing_text})

    # Add suggestions
    if validation_result.suggestions:
        suggestions_text = "**Suggestions:**\n" + "\n".join(
            f"• {suggestion}" for suggestion in validation_result.suggestions
        )
        body_parts.append({'type': 'message', 'text': suggestions_text})

    # Add action buttons
    buttons = [
        {
            'text': '✏️ Revise Issue',
            'value': f'revise_issue:{conversation.id}',
            'style': 'Primary'
        },
        {
            'text': '🚫 Cancel',
            'value': f'cancel:{conversation.id}',
            'style': 'Danger'
        }
    ]

    body_parts.append({'type': 'actions', 'items': buttons})

    try:
        issue_maker_bot.send_message({
            'head': {'text': f'{emoji} Validation Result'},
            'body': body_parts
        }, conversation.channel_jid or conversation.user_jid)
    except Exception as e:
        logger.error(f"Failed to send validation feedback: {e}")


def _create_github_issue(conversation, validation_result=None):
    """Create GitHub issue and notify user"""
    from bot_core.github_bot import github_bot
    from bot_core.issue_maker_bot import issue_maker_bot

    try:
        # Build issue body
        body_parts = []

        if conversation.description:
            body_parts.append(f"## Description\n{conversation.description}")

        if conversation.reproduction_steps:
            body_parts.append(f"## Reproduction Steps\n{conversation.reproduction_steps}")

        if conversation.environment:
            body_parts.append(f"## Environment\n{conversation.environment}")

        if conversation.expected_behavior:
            body_parts.append(f"## Expected Behavior\n{conversation.expected_behavior}")

        if conversation.actual_behavior:
            body_parts.append(f"## Actual Behavior\n{conversation.actual_behavior}")

        if conversation.screenshot_urls:
            screenshots_section = "## Screenshots\n" + "\n".join(
                f"![Screenshot {i+1}]({url})" for i, url in enumerate(conversation.screenshot_urls)
            )
            body_parts.append(screenshots_section)

        # Add metadata
        body_parts.append(f"\n---\n_Created by {conversation.user_jid} via Zoom Bot_")
        if validation_result:
            body_parts.append(f"_Quality Score: {validation_result.score}/100_")

        issue_body = "\n\n".join(body_parts) if body_parts else conversation.issue_description

        # Create GitHub issue
        result = github_bot.create_issue(
            repo=conversation.selected_app.github_repo,
            title=conversation.issue_title,
            body=issue_body
        )

        if result['success']:
            # Update conversation
            conversation.github_issue_url = result['html_url']
            conversation.github_issue_number = result['number']
            conversation.state = 'completed'
            conversation.save()

            # Build success message
            success_message = f"✅ Issue #{result['number']} created!\n🔗 {result['html_url']}"

            if validation_result:
                if validation_result.score >= 80:
                    success_message += f"\n\n💡 Quality Score: {validation_result.score}/100 (Excellent!)"
                elif validation_result.score >= 60:
                    success_message += f"\n\n💡 Quality Score: {validation_result.score}/100 (Good!)"
                else:
                    success_message += f"\n\n💡 Quality Score: {validation_result.score}/100"

            issue_maker_bot.send_message({
                'head': {'text': 'Issue Created'},
                'body': [{'type': 'message', 'text': success_message}]
            }, conversation.channel_jid or conversation.user_jid)

        else:
            # GitHub creation failed
            error_msg = result.get('error', 'Unknown error')
            issue_maker_bot.send_message({
                'head': {'text': 'Error'},
                'body': [{
                    'type': 'message',
                    'text': f'❌ Failed to create GitHub issue: {error_msg}'
                }]
            }, conversation.channel_jid or conversation.user_jid)

    except Exception as e:
        logger.error(f"Failed to create GitHub issue: {e}", exc_info=True)
        try:
            issue_maker_bot.send_message({
                'head': {'text': 'Error'},
                'body': [{
                    'type': 'message',
                    'text': f'❌ Error creating issue: {str(e)}'
                }]
            }, conversation.channel_jid or conversation.user_jid)
        except Exception:
            pass


@shared_task
def cleanup_old_conversations():
    """Delete conversations older than 30 days"""
    from bot_core.models import IssueConversation

    thirty_days_ago = timezone.now() - timedelta(days=30)

    deleted_count, _ = IssueConversation.objects.filter(
        state__in=['completed', 'cancelled'],
        created_at__lt=thirty_days_ago
    ).delete()

    logger.info(f"Deleted {deleted_count} old conversations")
    return deleted_count


@shared_task
def cleanup_validation_feedback():
    """Clear validation_feedback JSONField for old records to save space"""
    from bot_core.models import IssueConversation

    thirty_days_ago = timezone.now() - timedelta(days=30)

    updated_count = IssueConversation.objects.filter(
        validation_feedback__isnull=False,
        created_at__lt=thirty_days_ago
    ).update(validation_feedback=None)

    logger.info(f"Cleared validation feedback for {updated_count} old records")
    return updated_count
