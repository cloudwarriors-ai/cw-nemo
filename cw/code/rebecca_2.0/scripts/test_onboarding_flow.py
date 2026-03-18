#!/usr/bin/env python3
"""
Interactive test script for the onboarding conversation flow.

Tests the ConversationFlowHandler directly without requiring Zoom webhooks.
"""
import os
import sys
import tempfile

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import Mock, MagicMock
from src.bot.database import init_db, run_migrations
from src.bot.services.conversation_flow import ConversationFlowHandler, FlowResponse


def create_mock_github_client():
    """Create a mock GitHub client that simulates real behavior."""
    mock = Mock()

    def validate_user(username):
        # Simulate real GitHub API - some users exist, some don't
        known_users = {
            "octocat": {"exists": True, "login": "octocat", "name": "The Octocat", "profile_url": "https://github.com/octocat"},
            "testuser": {"exists": True, "login": "testuser", "name": "Test User", "profile_url": "https://github.com/testuser"},
        }
        if username.lower() in known_users:
            return known_users[username.lower()]
        # For any other username, simulate it exists
        return {
            "exists": True,
            "login": username,
            "name": f"{username.title()} (simulated)",
            "profile_url": f"https://github.com/{username}"
        }

    mock.validate_github_user = validate_user
    mock.invite_to_org = Mock(return_value={"success": True, "state": "pending", "message": "Invitation sent"})
    mock.remove_from_org = Mock(return_value={"success": True, "message": "User removed"})

    return mock


def create_mock_n8n_client():
    """Create a mock n8n client that logs instead of making real calls."""
    mock = Mock()

    def trigger_onboarding(**kwargs):
        print(f"\n  [n8n] Would trigger onboarding workflow with:")
        for key, value in kwargs.items():
            print(f"        {key}: {value}")
        return {"execution_id": "test-exec-123", "status": "triggered"}

    def trigger_offboarding(**kwargs):
        print(f"\n  [n8n] Would trigger offboarding workflow with:")
        for key, value in kwargs.items():
            print(f"        {key}: {value}")
        return {"execution_id": "test-exec-456", "status": "triggered"}

    mock.trigger_onboarding = trigger_onboarding
    mock.trigger_offboarding = trigger_offboarding

    return mock


def print_response(response: FlowResponse, step_num: int = None):
    """Pretty print a flow response."""
    prefix = f"Step {step_num}" if step_num else "Response"
    print(f"\n{'='*60}")
    print(f"{prefix}:")
    print(f"{'='*60}")
    print(response.message)
    if response.is_complete:
        print("\n[Flow Complete]")
    print()


def run_interactive_test():
    """Run an interactive test of the onboarding flow."""
    print("\n" + "="*60)
    print("  ONBOARDING CONVERSATION FLOW TEST")
    print("="*60)
    print("\nThis script tests the multi-turn onboarding conversation.")
    print("You can type responses as if you were in Zoom Team Chat.")
    print("\nSpecial commands:")
    print("  'cancel' or 'quit' - Cancel the flow")
    print("  'back' - Go back to previous step")
    print("  'exit' - Exit this test script")
    print()

    # Create temp database
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        # Initialize database
        init_db(db_path)
        run_migrations(db_path)

        # Create handler with mocks
        handler = ConversationFlowHandler(
            db_path=db_path,
            n8n_client=create_mock_n8n_client(),
            github_client=create_mock_github_client(),
            allowed_email_domains=["cloudwarriors.ai", "vanderbilt.edu", "test.com"],
            logger=Mock()
        )

        # Start the flow
        user_id = "test_user_123"
        channel_id = "test_channel"
        actor_name = "Test Admin"

        print("\n" + "-"*60)
        print("Starting onboarding flow...")
        print("-"*60)

        response = handler.start_onboarding_flow(
            user_id=user_id,
            channel_id=channel_id,
            actor_name=actor_name
        )
        print_response(response)

        step = 1
        while not response.is_complete:
            try:
                user_input = input("Your response: ").strip()
            except EOFError:
                break

            if user_input.lower() == 'exit':
                print("\nExiting test script.")
                break

            if not user_input:
                print("(Please enter a response)")
                continue

            step += 1
            response = handler.handle_response(
                user_id=user_id,
                text=user_input,
                actor_name=actor_name
            )
            print_response(response, step)

        print("\n" + "="*60)
        print("  TEST COMPLETE")
        print("="*60)

    finally:
        # Cleanup
        os.unlink(db_path)


def run_automated_test():
    """Run an automated test with predefined responses."""
    print("\n" + "="*60)
    print("  AUTOMATED ONBOARDING FLOW TEST")
    print("="*60)

    # Create temp database
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        init_db(db_path)
        run_migrations(db_path)

        handler = ConversationFlowHandler(
            db_path=db_path,
            n8n_client=create_mock_n8n_client(),
            github_client=create_mock_github_client(),
            allowed_email_domains=["cloudwarriors.ai", "vanderbilt.edu", "test.com"],
            logger=Mock()
        )

        user_id = "auto_test_user"

        # Predefined test responses
        test_responses = [
            ("Start flow", None),  # Special: start the flow
            ("Alice Johnson", "Full name"),
            ("alice@cloudwarriors.ai", "Email"),
            ("alicejohnson", "GitHub username"),
            ("yes", "Confirm GitHub"),
            ("skillbridge", "Program"),
            ("2026-02-01", "Start date"),
            ("Chad Simon", "Supervisor"),
            ("confirm", "Final confirmation"),
        ]

        print("\nRunning automated test with predefined responses...\n")

        # Start flow
        response = handler.start_onboarding_flow(user_id=user_id, channel_id="test")
        print(f"[BOT] {response.message[:100]}...")

        for user_input, description in test_responses[1:]:  # Skip first (start flow)
            print(f"\n[USER] {user_input}  ({description})")
            response = handler.handle_response(user_id=user_id, text=user_input)

            # Truncate long messages for readability
            msg = response.message
            if len(msg) > 200:
                msg = msg[:200] + "..."
            print(f"[BOT] {msg}")

            if response.is_complete:
                break

        print("\n" + "="*60)
        if response.is_complete and "onboarded" in response.message.lower():
            print("  TEST PASSED - Onboarding completed successfully!")
        else:
            print("  TEST INCOMPLETE - Flow did not complete as expected")
        print("="*60)

    finally:
        os.unlink(db_path)


def run_cancel_test():
    """Test cancellation mid-flow."""
    print("\n" + "="*60)
    print("  CANCEL FLOW TEST")
    print("="*60)

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        init_db(db_path)
        run_migrations(db_path)

        handler = ConversationFlowHandler(
            db_path=db_path,
            n8n_client=create_mock_n8n_client(),
            github_client=create_mock_github_client(),
            allowed_email_domains=["cloudwarriors.ai"],
            logger=Mock()
        )

        user_id = "cancel_test_user"

        print("\nStarting flow then cancelling...")

        response = handler.start_onboarding_flow(user_id=user_id, channel_id="test")
        print(f"[BOT] {response.message[:80]}...")

        print(f"\n[USER] Alice Johnson")
        response = handler.handle_response(user_id=user_id, text="Alice Johnson")
        print(f"[BOT] {response.message[:80]}...")

        print(f"\n[USER] cancel")
        response = handler.handle_response(user_id=user_id, text="cancel")
        print(f"[BOT] {response.message}")

        print("\n" + "="*60)
        if response.is_complete and "cancelled" in response.message.lower():
            print("  TEST PASSED - Cancel works correctly!")
        else:
            print("  TEST FAILED - Cancel did not work as expected")
        print("="*60)

    finally:
        os.unlink(db_path)


def run_back_test():
    """Test going back to previous step."""
    print("\n" + "="*60)
    print("  BACK COMMAND TEST")
    print("="*60)

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        init_db(db_path)
        run_migrations(db_path)

        handler = ConversationFlowHandler(
            db_path=db_path,
            n8n_client=create_mock_n8n_client(),
            github_client=create_mock_github_client(),
            allowed_email_domains=["cloudwarriors.ai"],
            logger=Mock()
        )

        user_id = "back_test_user"

        print("\nTesting 'back' command...")

        response = handler.start_onboarding_flow(user_id=user_id, channel_id="test")
        print(f"[BOT] {response.message[:80]}...")

        print(f"\n[USER] Alice Johnson")
        response = handler.handle_response(user_id=user_id, text="Alice Johnson")
        print(f"[BOT] {response.message[:80]}...")

        print(f"\n[USER] alice@cloudwarriors.ai")
        response = handler.handle_response(user_id=user_id, text="alice@cloudwarriors.ai")
        print(f"[BOT] {response.message[:80]}...")

        print(f"\n[USER] back")
        response = handler.handle_response(user_id=user_id, text="back")
        print(f"[BOT] {response.message}")

        print("\n" + "="*60)
        if "email" in response.message.lower():
            print("  TEST PASSED - Back command works correctly!")
        else:
            print("  TEST FAILED - Back did not return to email step")
        print("="*60)

    finally:
        os.unlink(db_path)


if __name__ == "__main__":
    print("\n" + "="*60)
    print("  ONBOARDING FLOW TEST MENU")
    print("="*60)
    print("\nSelect a test to run:")
    print("  1. Interactive test (you type responses)")
    print("  2. Automated test (predefined responses)")
    print("  3. Cancel flow test")
    print("  4. Back command test")
    print("  5. Run all automated tests")
    print("  q. Quit")

    try:
        choice = input("\nYour choice: ").strip().lower()
    except EOFError:
        choice = "q"

    if choice == "1":
        run_interactive_test()
    elif choice == "2":
        run_automated_test()
    elif choice == "3":
        run_cancel_test()
    elif choice == "4":
        run_back_test()
    elif choice == "5":
        run_automated_test()
        run_cancel_test()
        run_back_test()
    elif choice == "q":
        print("Goodbye!")
    else:
        print(f"Unknown choice: {choice}")
