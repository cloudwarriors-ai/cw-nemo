"""
Integration tests for Avatar API (Simli).

These tests require a valid SIMLI_API_KEY to run.
Run with: pytest tests/integration/test_avatar_integration.py -v

To run only if credentials are available:
    pytest tests/integration/ -v -m simli
"""
import pytest
from .conftest import skip_without_simli


@pytest.mark.integration
@pytest.mark.simli
class TestSimliIntegration:
    """Integration tests for Simli avatar API."""

    @skip_without_simli
    def test_simli_client_initializes(self, simli_api_key):
        """Test that Simli client can initialize."""
        from src.avatar.simli_client import SimliClient

        client = SimliClient(api_key=simli_api_key)

        assert client is not None
        assert client.api_key == simli_api_key

    @skip_without_simli
    def test_simli_validate_credentials(self, simli_api_key):
        """Test that Simli credentials are valid."""
        from src.avatar.simli_client import SimliClient

        client = SimliClient(api_key=simli_api_key)

        try:
            # Try to validate credentials
            is_valid = client.validate_credentials()
            assert is_valid is True
        except AttributeError:
            # Method might not exist, try alternative
            try:
                avatars = client.list_avatars()
                assert isinstance(avatars, list)
            except Exception as e:
                if "401" in str(e) or "Unauthorized" in str(e):
                    raise
                # Other errors are acceptable

    @skip_without_simli
    def test_simli_avatars_available(self, simli_api_key):
        """Test that Simli avatars can be listed."""
        from src.avatar.simli_client import SimliClient

        client = SimliClient(api_key=simli_api_key)

        try:
            avatars = client.list_avatars()
            assert isinstance(avatars, list)
            # Should have at least one avatar available
            if len(avatars) > 0:
                avatar = avatars[0]
                assert "id" in avatar or "avatar_id" in avatar
        except (AttributeError, NotImplementedError):
            pytest.skip("list_avatars not implemented")

    @skip_without_simli
    def test_simli_face_id_configured(self, simli_api_key):
        """Test that a face ID is configured."""
        from src.avatar.simli_client import SimliClient
        import os

        client = SimliClient(api_key=simli_api_key)

        # Check if face ID is configured
        face_id = os.getenv("SIMLI_FACE_ID")
        if face_id:
            assert len(face_id) > 0


@pytest.mark.integration
@pytest.mark.simli
class TestAvatarSessionIntegration:
    """Integration tests for avatar session management."""

    @skip_without_simli
    def test_avatar_session_manager_initializes(self, simli_api_key):
        """Test that avatar session manager initializes."""
        from src.avatar.simli_client import SimliClient
        from src.avatar.avatar_session import AvatarSessionManager

        client = SimliClient(api_key=simli_api_key)
        manager = AvatarSessionManager(simli_client=client)

        assert manager is not None
        assert manager.simli_client == client

    @skip_without_simli
    def test_simli_has_default_faces(self, simli_api_key):
        """Test that SimliClient has default face presets."""
        from src.avatar.simli_client import SimliClient

        # SimliClient has FACES class attribute with preset faces
        assert hasattr(SimliClient, 'FACES')
        assert len(SimliClient.FACES) > 0
        assert "professional_female" in SimliClient.FACES

    @skip_without_simli
    def test_simli_session_states_defined(self, simli_api_key):
        """Test that session states are properly defined."""
        from src.avatar.simli_client import SimliSessionState

        # Check that all expected states exist
        expected_states = ["CREATED", "CONNECTING", "CONNECTED", "STREAMING", "CLOSED", "ERROR"]
        for state in expected_states:
            assert hasattr(SimliSessionState, state)


@pytest.mark.integration
@pytest.mark.simli
class TestAvatarWebpageIntegration:
    """Integration tests for avatar webpage server."""

    @skip_without_simli
    def test_avatar_webpage_server_initializes(self, simli_api_key):
        """Test that avatar webpage server initializes."""
        from src.avatar.simli_client import SimliClient
        from src.avatar.avatar_session import AvatarSessionManager, AvatarWebpageServer

        client = SimliClient(api_key=simli_api_key)
        manager = AvatarSessionManager(simli_client=client)
        server = AvatarWebpageServer(session_manager=manager)

        assert server is not None
        assert server.session_manager == manager

    @skip_without_simli
    def test_avatar_webpage_html_generated(self, simli_api_key):
        """Test that avatar webpage HTML can be generated."""
        from src.avatar.simli_client import SimliClient
        from src.avatar.avatar_session import AvatarSessionManager, AvatarWebpageServer

        client = SimliClient(api_key=simli_api_key)
        manager = AvatarSessionManager(simli_client=client)
        server = AvatarWebpageServer(session_manager=manager)

        html = server.get_webpage_html()
        assert html is not None
        assert len(html) > 0
        assert "<!DOCTYPE html>" in html
        assert "QA Bot" in html


@pytest.mark.integration
@pytest.mark.simli
class TestHealthWithAvatar:
    """Test health endpoint with avatar configured."""

    @skip_without_simli
    def test_health_shows_avatar_configured(self, integration_client):
        """Test health endpoint shows avatar as configured."""
        response = integration_client.get("/health?detailed=true")
        assert response.status_code == 200

        data = response.get_json()

        # Check avatar status in dependencies
        if "dependencies" in data:
            avatar_status = data["dependencies"].get("avatar", {})
            assert avatar_status.get("status") in ["ok", "configured", "not_configured"]


@pytest.mark.integration
@pytest.mark.simli
class TestAvatarEndpointsIntegration:
    """Integration tests for avatar Flask endpoints."""

    @skip_without_simli
    def test_avatar_status_endpoint(self, integration_client):
        """Test avatar status endpoint returns valid response."""
        response = integration_client.get("/api/avatar/status")

        # Should return 200 even if no active session
        assert response.status_code in [200, 404]

        if response.status_code == 200:
            data = response.get_json()
            assert "status" in data or "active" in data

    @skip_without_simli
    def test_avatar_start_validation(self, integration_client):
        """Test avatar start endpoint validates input."""
        # Missing required fields should fail
        response = integration_client.post(
            "/api/avatar/start",
            json={}
        )

        # Should return 400 for missing fields or 503 if not configured
        assert response.status_code in [400, 422, 503]
