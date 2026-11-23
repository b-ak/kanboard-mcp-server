"""MCP tools exposing Kanboard to Claude."""

from __future__ import annotations

import base64
import mimetypes
from datetime import datetime
from typing import Annotated, Any, Literal

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.utilities.types import Image
from mcp.types import ToolAnnotations
from pydantic import Field

from .client import KanboardClient, KanboardError

READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=True)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True)

MAX_FILE_BYTES = 5 * 1024 * 1024
SUBTASK_STATUS = {"todo": 0, "in_progress": 1, "done": 2}

TaskId = Annotated[int, Field(gt=0, description="Kanboard task ID")]
ProjectId = Annotated[int, Field(gt=0, description="Kanboard project ID")]
Priority = Annotated[
    int, Field(ge=0, description="Priority; higher is more important (Kanboard default range 0-3)")
]
DueDate = Annotated[
    str,
    Field(description="Due date as 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM'; empty string clears it"),
]
ColumnRef = Annotated[str, Field(description="Column name (case-insensitive) or column ID")]
Color = Annotated[
    Literal[
        "yellow",
        "blue",
        "green",
        "purple",
        "red",
        "orange",
        "grey",
        "brown",
        "deep_orange",
        "dark_grey",
        "pink",
        "teal",
        "cyan",
        "lime",
        "light_green",
        "amber",
    ],
    Field(description="Kanboard color, shared by tags and task cards"),
]


# --------------------------------------------------------------------------- helpers


def fmt_ts(value: Any) -> str | None:
    """Convert a Kanboard Unix timestamp to ISO-8601 (server local time)."""
    try:
        ts = int(value or 0)
    except (TypeError, ValueError):
        return None
    if ts <= 0:
        return None
    return datetime.fromtimestamp(ts).astimezone().isoformat(timespec="minutes")


def parse_due(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d %H:%M")
        except ValueError:
            continue
    raise ToolError(f"Invalid due date {value!r}; use 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM'")


def compact_task(task: dict[str, Any], columns: dict[int, str] | None = None) -> dict[str, Any]:
    column_id = int(task.get("column_id") or 0)
    out = {
        "id": int(task["id"]),
        "title": task.get("title"),
        "status": "open" if str(task.get("is_active", "1")) == "1" else "closed",
        "priority": int(task.get("priority") or 0),
        "column": (columns or {}).get(column_id) or task.get("column_name") or column_id,
        "assignee": task.get("assignee_username") or task.get("assignee_name"),
        "due": fmt_ts(task.get("date_due")),
        "project_id": int(task.get("project_id") or 0) or None,
    }
    if task.get("project_name"):
        out["project"] = task["project_name"]
    return {k: v for k, v in out.items() if v is not None}


class Kanboard:
    """Higher-level helpers shared by the tools."""

    def __init__(self, client: KanboardClient):
        self.client = client
        self._me: dict[str, Any] | None = None

    def call(self, method: str, **params: Any) -> Any:
        try:
            return self.client.call(method, **params)
        except KanboardError as exc:
            raise ToolError(str(exc)) from exc

    def require(self, result: Any, what: str) -> Any:
        if result in (None, False, [], {}):
            raise ToolError(f"{what} failed or was not found")
        return result

    def get_task(self, task_id: int) -> dict[str, Any]:
        return self.require(self.call("getTask", task_id=task_id), f"Task {task_id}")

    def projects(self) -> list[dict[str, Any]]:
        method = "getAllProjects" if self.client.is_app_api else "getMyProjects"
        return self.call(method) or []

    def columns(self, project_id: int) -> list[dict[str, Any]]:
        cols = self.call("getColumns", project_id=project_id) or []
        return sorted(cols, key=lambda c: int(c.get("position") or 0))

    def column_names(self, project_id: int) -> dict[int, str]:
        return {int(c["id"]): c["title"] for c in self.columns(project_id)}

    def resolve_column(self, project_id: int, ref: str) -> int:
        cols = self.columns(project_id)
        ref = ref.strip()
        for c in cols:
            if ref == str(c["id"]) or ref.lower() == str(c["title"]).lower():
                return int(c["id"])
        names = ", ".join(c["title"] for c in cols)
        raise ToolError(f"No column {ref!r} in project {project_id}. Columns: {names}")

    def current_user_id(self) -> int:
        if not self.client.is_app_api:
            if self._me is None:
                self._me = self.require(self.call("getMe"), "getMe")
            return int(self._me["id"])
        if self.client.config.default_user_id:
            return self.client.config.default_user_id
        raise ToolError(
            "Commenting with the application API token needs KANBOARD_DEFAULT_USER_ID, "
            "or use a personal access token (KANBOARD_USERNAME=<you>)."
        )


# --------------------------------------------------------------------------- tools


def register_tools(mcp: FastMCP, client: KanboardClient) -> None:
    kb = Kanboard(client)

    # ---- discovery -------------------------------------------------------------

    @mcp.tool(annotations=READ_ONLY)
    def get_me() -> dict[str, Any]:
        """Show which Kanboard user/API mode this server is connected as."""
        info: dict[str, Any] = {
            "kanboard_url": client.config.url,
            "api_mode": "application" if client.is_app_api else "user",
            "kanboard_version": kb.call("getVersion"),
        }
        if not client.is_app_api:
            me = kb.call("getMe") or {}
            info["user"] = {k: me.get(k) for k in ("id", "username", "name", "email", "role")}
        return info

    @mcp.tool(annotations=READ_ONLY)
    def list_projects(include_inactive: bool = False) -> list[dict[str, Any]]:
        """List Kanboard projects (ID, name, board URL). Start here to find project IDs."""
        out = []
        for p in kb.projects():
            if not include_inactive and str(p.get("is_active", "1")) != "1":
                continue
            url = p.get("url")
            out.append(
                {
                    "id": int(p["id"]),
                    "name": p.get("name"),
                    "identifier": p.get("identifier") or None,
                    "active": str(p.get("is_active", "1")) == "1",
                    "board_url": url.get("board") if isinstance(url, dict) else None,
                }
            )
        return out

    @mcp.tool(annotations=READ_ONLY)
    def get_board(project_id: ProjectId) -> dict[str, Any]:
        """Show a project's board: each column with its open tasks, in order."""
        columns = kb.columns(project_id)
        tasks = kb.call("getAllTasks", project_id=project_id, status_id=1) or []
        tasks.sort(key=lambda t: (int(t.get("swimlane_id") or 0), int(t.get("position") or 0)))
        by_column: dict[int, list[dict[str, Any]]] = {int(c["id"]): [] for c in columns}
        for t in tasks:
            entry = compact_task(t)
            entry.pop("column", None)
            entry.pop("project_id", None)
            by_column.setdefault(int(t.get("column_id") or 0), []).append(entry)
        return {
            "project_id": project_id,
            "columns": [
                {
                    "id": int(c["id"]),
                    "title": c["title"],
                    "task_limit": int(c.get("task_limit") or 0) or None,
                    "tasks": by_column.get(int(c["id"]), []),
                }
                for c in columns
            ],
        }

    @mcp.tool(annotations=READ_ONLY)
    def list_tasks(
        project_id: ProjectId,
        status: Literal["open", "closed", "all"] = "open",
        column: Annotated[str | None, Field(description="Optional column name or ID")] = None,
    ) -> list[dict[str, Any]]:
        """List tasks in a project, optionally filtered by status and column."""
        statuses = {"open": [1], "closed": [0], "all": [1, 0]}[status]
        tasks: list[dict[str, Any]] = []
        for status_id in statuses:
            tasks += kb.call("getAllTasks", project_id=project_id, status_id=status_id) or []
        names = kb.column_names(project_id)
        if column:
            column_id = kb.resolve_column(project_id, column)
            tasks = [t for t in tasks if int(t.get("column_id") or 0) == column_id]
        return [compact_task(t, names) for t in sorted(tasks, key=lambda t: int(t["id"]))]

    @mcp.tool(annotations=READ_ONLY)
    def search_tasks(
        query: Annotated[
            str,
            Field(
                description=(
                    "Kanboard filter syntax, e.g. 'status:open assignee:me', "
                    "'due:<=today', 'column:\"In progress\"', 'tag:bug priority:3', "
                    "or plain words to match titles."
                )
            ),
        ],
        project_id: Annotated[
            int | None, Field(gt=0, description="Limit to one project; omit to search all")
        ] = None,
    ) -> list[dict[str, Any]]:
        """Search tasks with Kanboard's filter syntax across one or all projects."""
        project_ids = [project_id] if project_id else [int(p["id"]) for p in kb.projects()]
        results = []
        for pid in project_ids:
            for t in kb.call("searchTasks", project_id=pid, query=query) or []:
                results.append(compact_task(t))
        return results

    @mcp.tool(annotations=READ_ONLY)
    def get_overdue_tasks(
        project_id: Annotated[int | None, Field(gt=0, description="Optional project ID")] = None,
    ) -> list[dict[str, Any]]:
        """List open tasks whose due date has passed."""
        if project_id:
            tasks = kb.call("getOverdueTasksByProject", project_id=project_id)
        elif client.is_app_api:
            tasks = kb.call("getOverdueTasks")
        else:
            tasks = kb.call("getMyOverdueTasks")
        return [compact_task(t) for t in tasks or []]

    @mcp.tool(annotations=READ_ONLY)
    def list_project_users(project_id: ProjectId) -> dict[str, str]:
        """List users that can be assigned tasks in a project, as {user_id: name}."""
        return kb.call("getAssignableUsers", project_id=project_id) or {}

    # ---- tags --------------------------------------------------------------

    @mcp.tool(annotations=READ_ONLY)
    def list_tags(project_id: ProjectId) -> list[dict[str, Any]]:
        """List tags defined on a project, with their color (null if none is set)."""
        tags = kb.call("getTagsByProject", project_id=project_id) or []
        return [
            {"id": int(t["id"]), "name": t["name"], "color": t.get("color_id") or None}
            for t in tags
        ]

    @mcp.tool(annotations=WRITE)
    def create_tag(
        project_id: ProjectId,
        tag: Annotated[str, Field(min_length=1, description="Tag name")],
        color: Color | None = None,
    ) -> dict[str, Any]:
        """Create a project tag, optionally with a color."""
        params: dict[str, Any] = {"project_id": project_id, "tag": tag}
        if color is not None:
            params["color_id"] = color
        tag_id = kb.require(kb.call("createTag", **params), "createTag")
        return {"id": int(tag_id), "name": tag, "color": color}

    @mcp.tool(annotations=WRITE)
    def update_tag(
        tag_id: Annotated[int, Field(gt=0, description="Kanboard tag ID, from list_tags")],
        tag: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "Tag name. Kanboard requires this on every call; pass the tag's "
                    "current name again if you only want to change its color."
                ),
            ),
        ],
        color: Annotated[
            Color | None, Field(description="New color; omit to keep the current one")
        ] = None,
    ) -> str:
        """Rename a tag and/or set its color."""
        if color is None:
            # Kanboard's updateTag overwrites color_id with null when it is omitted,
            # so look up the current color and send it back unchanged.
            tags = kb.call("getAllTags") or []
            current = next((t for t in tags if int(t["id"]) == tag_id), None)
            if current is None:
                raise ToolError(f"Tag {tag_id} not found")
            color = current.get("color_id") or None
        params: dict[str, Any] = {"tag_id": tag_id, "tag": tag}
        if color is not None:
            params["color_id"] = color
        kb.require(kb.call("updateTag", **params), f"Updating tag {tag_id}")
        return f"Tag {tag_id} updated"

    # ---- task details ----------------------------------------------------------

    @mcp.tool(annotations=READ_ONLY)
    def get_task(
        task_id: TaskId,
        max_comments: Annotated[
            int, Field(ge=0, le=200, description="How many of the most recent comments to include")
        ] = 30,
    ) -> dict[str, Any]:
        """Get everything about a task: details, tags, subtasks, comments and attachments.

        Use this to summarise or review a task's progress.
        """
        t = kb.get_task(task_id)
        project_id = int(t["project_id"])
        project = kb.call("getProjectById", project_id=project_id) or {}
        comments = kb.call("getAllComments", task_id=task_id) or []
        subtasks = kb.call("getAllSubtasks", task_id=task_id) or []
        files = kb.call("getAllTaskFiles", task_id=task_id) or []
        tags = kb.call("getTaskTags", task_id=task_id) or {}

        return {
            **compact_task(t, kb.column_names(project_id)),
            "project": project.get("name"),
            "description": t.get("description") or "",
            "url": t.get("url"),
            "tags": list(tags.values()) if isinstance(tags, dict) else tags,
            "category_id": int(t.get("category_id") or 0) or None,
            "color": t.get("color_id"),
            "created": fmt_ts(t.get("date_creation")),
            "modified": fmt_ts(t.get("date_modification")),
            "started": fmt_ts(t.get("date_started")),
            "completed": fmt_ts(t.get("date_completed")),
            "time_estimated_h": float(t.get("time_estimated") or 0),
            "time_spent_h": float(t.get("time_spent") or 0),
            "subtasks": [
                {
                    "id": int(s["id"]),
                    "title": s.get("title"),
                    "status": s.get("status_name"),
                    "assignee": s.get("username") or s.get("name"),
                }
                for s in subtasks
            ],
            "comments": [
                {
                    "id": int(c["id"]),
                    "author": c.get("name") or c.get("username"),
                    "date": fmt_ts(c.get("date_creation")),
                    "text": c.get("comment"),
                }
                for c in (comments[-max_comments:] if max_comments else [])
            ],
            "comment_count": len(comments),
            "attachments": [
                {
                    "file_id": int(f["id"]),
                    "name": f.get("name"),
                    "size_bytes": int(f.get("size") or 0),
                    "is_image": str(f.get("is_image")) == "1",
                }
                for f in files
            ],
        }

    @mcp.tool(annotations=READ_ONLY)
    def get_task_file(
        file_id: Annotated[int, Field(gt=0, description="Attachment file_id from get_task")],
    ) -> Image | str:
        """Read a task attachment: images are returned as images, text files as text."""
        meta = kb.require(kb.call("getTaskFile", file_id=file_id), f"File {file_id}")
        name = meta.get("name") or f"file-{file_id}"
        size = int(meta.get("size") or 0)
        if size > MAX_FILE_BYTES:
            raise ToolError(f"{name} is {size} bytes; the limit is {MAX_FILE_BYTES} bytes")
        raw = base64.b64decode(kb.call("downloadTaskFile", file_id=file_id) or "")
        if str(meta.get("is_image")) == "1":
            ext = name.rsplit(".", 1)[-1].lower() if "." in name else "png"
            return Image(data=raw, format="jpeg" if ext == "jpg" else ext)
        mime = mimetypes.guess_type(name)[0] or ""
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            return f"{name} ({mime or 'binary'}, {size} bytes) is not a text file."
        return f"--- {name} ---\n{text}"

    # ---- task writes -----------------------------------------------------------

    @mcp.tool(annotations=WRITE)
    def create_task(
        project_id: ProjectId,
        title: Annotated[str, Field(min_length=1, description="Task title")],
        description: Annotated[
            str, Field(description="Full task description; Markdown supported")
        ] = "",
        priority: Priority | None = None,
        column: ColumnRef | None = None,
        owner_id: Annotated[int | None, Field(gt=0, description="Assignee user ID")] = None,
        due_date: DueDate | None = None,
        tags: Annotated[
            list[str] | None,
            Field(description="Tag names to apply; tags that don't exist yet are created"),
        ] = None,
        color: Annotated[Color | None, Field(description="Card color")] = None,
    ) -> dict[str, Any]:
        """Create a task in a project.

        Defaults to the project's first column when `column` is omitted. Use
        list_projects to find the project_id, and list_project_users for a
        valid owner_id. Returns the created task's details, including its URL.
        """
        params: dict[str, Any] = {"project_id": project_id, "title": title.strip()}
        if description:
            params["description"] = description
        if priority is not None:
            params["priority"] = priority
        if column:
            params["column_id"] = kb.resolve_column(project_id, column)
        if owner_id:
            params["owner_id"] = owner_id
        if due_date:
            params["date_due"] = parse_due(due_date)
        if tags:
            params["tags"] = tags
        if color:
            params["color_id"] = color
        task_id = kb.require(kb.call("createTask", **params), "createTask")
        task = kb.get_task(int(task_id))
        return {**compact_task(task, kb.column_names(project_id)), "url": task.get("url")}

    @mcp.tool(annotations=WRITE)
    def update_task(
        task_id: TaskId,
        title: Annotated[str | None, Field(description="New task title")] = None,
        description: Annotated[
            str | None, Field(description="New full task description; Markdown supported")
        ] = None,
        priority: Priority | None = None,
        owner_id: Annotated[
            int | None, Field(ge=0, description="Assignee user ID; 0 unassigns")
        ] = None,
        due_date: DueDate | None = None,
        tags: Annotated[list[str] | None, Field(description="Replaces all tags")] = None,
        color: Annotated[Color | None, Field(description="Card color")] = None,
    ) -> dict[str, Any]:
        """Update task fields. Only the fields you pass are changed."""
        params: dict[str, Any] = {}
        if title is not None:
            params["title"] = title
        if description is not None:
            params["description"] = description
        if priority is not None:
            params["priority"] = priority
        if owner_id is not None:
            params["owner_id"] = owner_id
        if due_date is not None:
            params["date_due"] = parse_due(due_date)
        if tags is not None:
            params["tags"] = tags
        if color is not None:
            params["color_id"] = color
        if not params:
            raise ToolError("Nothing to update")
        kb.require(kb.call("updateTask", id=task_id, **params), f"Updating task {task_id}")
        task = kb.get_task(task_id)
        return compact_task(task, kb.column_names(int(task["project_id"])))

    @mcp.tool(annotations=WRITE)
    def move_task(
        task_id: TaskId,
        column: ColumnRef,
        position: Annotated[
            int | None, Field(gt=0, description="1 = top; omit to put it at the bottom")
        ] = None,
    ) -> dict[str, Any]:
        """Move a task to another column of its board (e.g. 'In progress', 'Done')."""
        task = kb.get_task(task_id)
        project_id = int(task["project_id"])
        swimlane_id = int(task.get("swimlane_id") or 0)
        column_id = kb.resolve_column(project_id, column)
        if position is None:
            siblings = [
                t
                for t in kb.call("getAllTasks", project_id=project_id, status_id=1) or []
                if int(t.get("column_id") or 0) == column_id
                and int(t.get("swimlane_id") or 0) == swimlane_id
                and int(t["id"]) != task_id
            ]
            position = len(siblings) + 1
        kb.require(
            kb.call(
                "moveTaskPosition",
                project_id=project_id,
                task_id=task_id,
                column_id=column_id,
                position=position,
                swimlane_id=swimlane_id,
            ),
            f"Moving task {task_id}",
        )
        return compact_task(kb.get_task(task_id), kb.column_names(project_id))

    @mcp.tool(annotations=WRITE)
    def close_task(task_id: TaskId) -> str:
        """Close (complete) a task. It can be reopened with reopen_task."""
        kb.require(kb.call("closeTask", task_id=task_id), f"Closing task {task_id}")
        return f"Task {task_id} closed"

    @mcp.tool(annotations=WRITE)
    def reopen_task(task_id: TaskId) -> str:
        """Reopen a closed task."""
        kb.require(kb.call("openTask", task_id=task_id), f"Reopening task {task_id}")
        return f"Task {task_id} reopened"

    @mcp.tool(annotations=WRITE)
    def add_comment(
        task_id: TaskId,
        content: Annotated[
            str, Field(min_length=1, description="Comment text; Markdown supported")
        ],
    ) -> str:
        """Add a comment (Markdown supported) to a task, e.g. a progress log entry."""
        comment_id = kb.require(
            kb.call(
                "createComment",
                task_id=task_id,
                user_id=kb.current_user_id(),
                content=content,
            ),
            "createComment",
        )
        return f"Comment {comment_id} added to task {task_id}"

    # ---- subtasks --------------------------------------------------------------

    @mcp.tool(annotations=WRITE)
    def create_subtask(
        task_id: TaskId,
        title: Annotated[str, Field(min_length=1, description="Subtask title")],
        user_id: Annotated[int | None, Field(gt=0, description="Assignee user ID")] = None,
        time_estimated: Annotated[float | None, Field(ge=0, description="Hours")] = None,
    ) -> str:
        """Add a subtask (checklist item) to an existing task.

        Subtasks are lightweight items in a task's checklist, distinct from
        full Kanboard tasks; use create_task instead when the work needs its
        own card on the board. time_estimated is informational only and does
        not affect scheduling.
        """
        params: dict[str, Any] = {"task_id": task_id, "title": title}
        if user_id:
            params["user_id"] = user_id
        if time_estimated:
            params["time_estimated"] = time_estimated
        subtask_id = kb.require(kb.call("createSubtask", **params), "createSubtask")
        return f"Subtask {subtask_id} created on task {task_id}"

    @mcp.tool(annotations=WRITE)
    def update_subtask(
        subtask_id: Annotated[int, Field(gt=0, description="Subtask ID, from get_task")],
        task_id: TaskId,
        status: Literal["todo", "in_progress", "done"] | None = None,
        title: Annotated[str | None, Field(description="New subtask title")] = None,
    ) -> str:
        """Change a subtask's status and/or title.

        Get subtask_id from get_task's "subtasks" list. At least one of
        status or title must be provided.
        """
        params: dict[str, Any] = {"id": subtask_id, "task_id": task_id}
        if status is not None:
            params["status"] = SUBTASK_STATUS[status]
        if title is not None:
            params["title"] = title
        if len(params) == 2:
            raise ToolError("Nothing to update")
        kb.require(kb.call("updateSubtask", **params), f"Updating subtask {subtask_id}")
        return f"Subtask {subtask_id} updated"
