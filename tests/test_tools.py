import asyncio
import base64

import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError

from kanboard_mcp.tools import register_tools

from .conftest import make_client

COLUMNS = [
    {"id": "2", "title": "Work in progress", "position": "2", "task_limit": "0"},
    {"id": "1", "title": "Backlog", "position": "1", "task_limit": "0"},
    {"id": "3", "title": "Done", "position": "3", "task_limit": "0"},
]


def task(id, column_id="1", active="1", **extra):
    return {
        "id": str(id),
        "title": f"Task {id}",
        "project_id": "1",
        "column_id": column_id,
        "swimlane_id": "0",
        "is_active": active,
        "priority": "0",
        "date_due": "0",
        "position": "1",
        **extra,
    }


def call(fake, tool, username="alice", **args):
    mcp = FastMCP("test")
    register_tools(mcp, make_client(fake, username))

    async def run():
        async with Client(mcp) as c:
            result = await c.call_tool(tool, args)
            return result

    return asyncio.run(run())


def test_list_tasks_all_fetches_open_and_closed(fake):
    fake.on("getColumns", COLUMNS)
    fake.on(
        "getAllTasks",
        fn=lambda project_id, status_id: [task(1)] if status_id == 1 else [task(2, active="0")],
    )
    result = call(fake, "list_tasks", project_id=1, status="all")
    assert [(t["id"], t["status"], t["column"]) for t in result.data] == [
        (1, "open", "Backlog"),
        (2, "closed", "Backlog"),
    ]


def test_create_task_resolves_column_and_due_date(fake):
    fake.on("getColumns", COLUMNS)
    fake.on("createTask", 42)
    fake.on("getTask", task(42, column_id="2", url="http://kb/t/42"))
    result = call(
        fake,
        "create_task",
        project_id=1,
        title="Write docs",
        column="work in progress",
        due_date="2026-12-01",
        tags=["docs"],
    )
    params = dict(fake.calls)["createTask"]
    assert params["column_id"] == 2
    assert params["date_due"] == "2026-12-01 00:00"
    assert params["tags"] == ["docs"]
    assert result.data["column"] == "Work in progress"


def test_unknown_column_lists_choices(fake):
    fake.on("getColumns", COLUMNS)
    with pytest.raises(ToolError, match="Backlog, Work in progress, Done"):
        call(fake, "create_task", project_id=1, title="x", column="Review")


def test_move_task_appends_to_bottom(fake):
    fake.on("getColumns", COLUMNS)
    fake.on("getTask", task(5))
    fake.on("getAllTasks", [task(6, column_id="3"), task(7, column_id="3"), task(5)])
    fake.on("moveTaskPosition", True)
    call(fake, "move_task", task_id=5, column="Done")
    params = dict(fake.calls)["moveTaskPosition"]
    assert params == {
        "project_id": 1,
        "task_id": 5,
        "column_id": 3,
        "position": 3,
        "swimlane_id": 0,
    }


def test_add_comment_uses_current_user(fake):
    fake.on("getMe", {"id": "9", "username": "alice"})
    fake.on("createComment", 11)
    call(fake, "add_comment", task_id=5, content="Progress")
    assert dict(fake.calls)["createComment"] == {"task_id": 5, "user_id": 9, "content": "Progress"}


def test_add_comment_with_app_token_needs_default_user(fake):
    with pytest.raises(ToolError, match="KANBOARD_DEFAULT_USER_ID"):
        call(fake, "add_comment", username="jsonrpc", task_id=5, content="x")


def test_get_task_includes_context(fake):
    fake.on("getColumns", COLUMNS)
    fake.on("getTask", task(5, description="desc", date_due="1767225600"))
    fake.on("getProjectById", {"id": "1", "name": "Home"})
    fake.on(
        "getAllComments",
        [{"id": "1", "name": "Alice", "comment": "started", "date_creation": "1767225600"}],
    )
    fake.on("getAllSubtasks", [{"id": "3", "title": "sub", "status_name": "Done"}])
    fake.on("getAllTaskFiles", [{"id": "8", "name": "shot.png", "size": "10", "is_image": "1"}])
    fake.on("getTaskTags", {"1": "bug"})
    data = call(fake, "get_task", task_id=5).structured_content
    assert data["project"] == "Home"
    assert data["tags"] == ["bug"]
    assert data["comments"][0]["text"] == "started"
    assert data["attachments"][0] == {
        "file_id": 8,
        "name": "shot.png",
        "size_bytes": 10,
        "is_image": True,
    }
    assert data["due"].startswith("2026-")


def test_get_task_file_text(fake):
    fake.on("getTaskFile", {"id": "8", "name": "notes.txt", "size": "5", "is_image": "0"})
    fake.on("downloadTaskFile", base64.b64encode(b"hello").decode())
    result = call(fake, "get_task_file", file_id=8)
    assert "hello" in result.content[0].text


def test_rpc_error_surfaces_as_tool_error(fake):
    with pytest.raises(ToolError, match="getTask failed: Method not found"):
        call(fake, "get_task", task_id=1)


def test_bad_credentials_message(fake):
    fake.status_code = 401
    with pytest.raises(ToolError, match="rejected the credentials"):
        call(fake, "list_projects")


def test_list_projects_uses_my_projects_for_user_api(fake):
    fake.on("getMyProjects", [{"id": "1", "name": "Home", "is_active": "1", "url": {"board": "b"}}])
    result = call(fake, "list_projects")
    assert result.structured_content["result"][0]["board_url"] == "b"
    assert fake.methods() == ["getMyProjects"]
