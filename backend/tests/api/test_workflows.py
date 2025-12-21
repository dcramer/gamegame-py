"""Workflow monitoring endpoint tests."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from gamegame.models import Game, Resource, WorkflowRun, WorkflowStatus
from gamegame.models.resource import ResourceStatus
from tests.conftest import AuthenticatedClient


@pytest.fixture
async def game(session):
    """Create a test game."""
    game = Game(name="Test Game", slug="test-game")
    session.add(game)
    await session.commit()
    await session.refresh(game)
    return game


@pytest.fixture
async def resource(session, game):
    """Create a test resource."""
    resource = Resource(
        game_id=game.id,
        name="Test Resource",
        original_filename="test.pdf",
        url="/uploads/test.pdf",
        content="",
        status=ResourceStatus.PROCESSING,
    )
    session.add(resource)
    await session.commit()
    await session.refresh(resource)
    return resource


@pytest.fixture
async def workflow_run(session, resource):
    """Create a test workflow run."""
    workflow = WorkflowRun(
        run_id="test-run-123",
        workflow_name="process_resource",
        status=WorkflowStatus.RUNNING,
        started_at=datetime.now(UTC),
        resource_id=resource.id,
        input_data={"resource_id": resource.id},
    )
    session.add(workflow)
    await session.commit()
    await session.refresh(workflow)
    return workflow


@pytest.mark.asyncio
async def test_list_workflows_requires_admin(authenticated_client: AuthenticatedClient):
    """Test that listing workflows requires admin."""
    response = await authenticated_client.get("/api/admin/workflows")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_list_workflows_unauthenticated(client: AsyncClient):
    """Test that listing workflows requires authentication."""
    response = await client.get("/api/admin/workflows")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_list_workflows_empty(admin_client: AuthenticatedClient):
    """Test listing workflows when empty."""
    response = await admin_client.get("/api/admin/workflows")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_list_workflows(admin_client: AuthenticatedClient, workflow_run):
    """Test listing workflows."""
    response = await admin_client.get("/api/admin/workflows")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["run_id"] == "test-run-123"
    assert data[0]["workflow_name"] == "process_resource"
    assert data[0]["status"] == "running"


@pytest.mark.asyncio
async def test_list_workflows_filter_by_run_id(admin_client: AuthenticatedClient, session, workflow_run):
    """Test filtering workflows by run ID."""
    # Create another workflow
    workflow2 = WorkflowRun(
        run_id="other-run-456",
        workflow_name="process_resource",
        status=WorkflowStatus.COMPLETED,
    )
    session.add(workflow2)
    await session.commit()

    response = await admin_client.get("/api/admin/workflows?runId=test-run-123")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["run_id"] == "test-run-123"


@pytest.mark.asyncio
async def test_list_workflows_filter_by_status(admin_client: AuthenticatedClient, session, workflow_run):
    """Test filtering workflows by status."""
    # Create completed workflow
    workflow2 = WorkflowRun(
        run_id="completed-run",
        workflow_name="process_resource",
        status=WorkflowStatus.COMPLETED,
    )
    session.add(workflow2)
    await session.commit()

    response = await admin_client.get("/api/admin/workflows?status=completed")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["run_id"] == "completed-run"


@pytest.mark.asyncio
async def test_get_workflow_by_run_id(admin_client: AuthenticatedClient, workflow_run):
    """Test getting a workflow by run ID."""
    response = await admin_client.get("/api/admin/workflows/test-run-123")
    assert response.status_code == 200
    data = response.json()
    assert data["run_id"] == "test-run-123"
    assert data["workflow_name"] == "process_resource"


@pytest.mark.asyncio
async def test_get_workflow_by_local_id(admin_client: AuthenticatedClient, workflow_run):
    """Test getting a workflow by local ID."""
    response = await admin_client.get(f"/api/admin/workflows/{workflow_run.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["run_id"] == "test-run-123"


@pytest.mark.asyncio
async def test_get_workflow_not_found(admin_client: AuthenticatedClient):
    """Test getting a non-existent workflow."""
    response = await admin_client.get("/api/admin/workflows/nonexistent-run")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_retry_workflow_requires_admin(authenticated_client: AuthenticatedClient):
    """Test that retrying workflow requires admin."""
    response = await authenticated_client.post("/api/admin/workflows/test-run/retry")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_retry_workflow_not_found(admin_client: AuthenticatedClient):
    """Test retrying a non-existent workflow."""
    response = await admin_client.post("/api/admin/workflows/nonexistent/retry")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_retry_workflow_not_failed(admin_client: AuthenticatedClient, workflow_run):
    """Test retrying a workflow that isn't failed."""
    response = await admin_client.post(f"/api/admin/workflows/{workflow_run.run_id}/retry")
    assert response.status_code == 400
    assert "failed" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_retry_workflow_success(admin_client: AuthenticatedClient, session, resource):
    """Test successfully retrying a failed workflow."""
    # Create failed workflow
    failed_workflow = WorkflowRun(
        run_id="failed-run-123",
        workflow_name="process_resource",
        status=WorkflowStatus.FAILED,
        resource_id=resource.id,
        error="Processing failed",
    )
    session.add(failed_workflow)
    await session.commit()

    with patch("gamegame.api.workflows.queue") as mock_queue:
        mock_job = AsyncMock()
        mock_job.id = "new-run-456"
        mock_queue.enqueue = AsyncMock(return_value=mock_job)

        response = await admin_client.post("/api/admin/workflows/failed-run-123/retry")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["run_id"] == "new-run-456"


@pytest.mark.asyncio
async def test_cancel_workflow_requires_admin(authenticated_client: AuthenticatedClient):
    """Test that cancelling workflow requires admin."""
    response = await authenticated_client.delete("/api/admin/workflows/test-run")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_cancel_workflow_not_found(admin_client: AuthenticatedClient):
    """Test cancelling a non-existent workflow."""
    response = await admin_client.delete("/api/admin/workflows/nonexistent")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_cancel_workflow_already_completed(admin_client: AuthenticatedClient, session):
    """Test cancelling a completed workflow."""
    completed_workflow = WorkflowRun(
        run_id="completed-run",
        workflow_name="process_resource",
        status=WorkflowStatus.COMPLETED,
    )
    session.add(completed_workflow)
    await session.commit()

    response = await admin_client.delete("/api/admin/workflows/completed-run")
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_cancel_workflow_success(admin_client: AuthenticatedClient, session, workflow_run, resource):
    """Test successfully cancelling a running workflow."""
    with patch("gamegame.api.workflows.queue") as mock_queue:
        mock_job = AsyncMock()
        mock_job.abort = AsyncMock()
        mock_queue.job = AsyncMock(return_value=mock_job)

        response = await admin_client.delete(f"/api/admin/workflows/{workflow_run.run_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    # Verify workflow was marked as cancelled
    await session.refresh(workflow_run)
    assert workflow_run.status == WorkflowStatus.CANCELLED

    # Verify resource was reset
    await session.refresh(resource)
    assert resource.status == ResourceStatus.READY
