# Telling Claude when to use Kanboard

Connecting the Kanboard MCP server gives Claude the tools; it doesn't tell Claude *when* to create,
move or comment on tasks. Write that down where Claude will read it:

- **Claude Code:** in the `CLAUDE.md` at the root of the project you work on (create it if it
  doesn't exist, or add the block below as a new section).
- **claude.ai / mobile:** in the instructions of a claude.ai Project, with the Kanboard connector
  enabled in it.

The template below lets Claude read the board freely and asks for your OK before every change.
Replace the placeholders: get the project ID with *"list my Kanboard projects"* and the column names
with *"show the board"*.

```markdown
## Kanboard task tracking

Work on this project is tracked in Kanboard project **<project name>** (project ID `<id>`) through
the `kanboard` MCP server. Board columns, in order: **<Backlog> → <Ready> → <Work in progress> →
<Done>**.

### Reading (no permission needed)
- Use `get_board`, `list_tasks`, `search_tasks`, `get_task` freely to understand current work.
- Before starting on something, check whether a matching task already exists
  (`search_tasks` with `project_id: <id>`) and mention its task ID.

### Changing the board (always ask first)
Never change anything on the board without my explicit OK. Propose the exact change, then wait:

- **New work or a bug comes up** → propose a task in **<Backlog>** with title, a short
  description, and priority (0–3, higher = more important).
- **Starting work on a task** → propose moving it to **<Work in progress>**.
- **End of a work session** → propose a progress comment: what was done, what's left, and the
  relevant files or commits.
- **Task finished** → propose moving it to **<Done>** and closing it (both, so Done tasks are
  never left open).

Several changes can be proposed together as one list and approved at once.
Don't change assignee, due date or tags unless I ask. Never delete tasks or comments.
```

## Notes

- **Column vs. status.** In Kanboard, moving a task to the Done column doesn't close it. Closed is
  a separate status, which is why the template moves *and* closes. Open tasks sitting in Done keep
  showing up in "open task" searches and overdue lists.
- **Permission prompts on claude.ai.** claude.ai also asks before each tool that changes something.
  With these rules you would confirm every change twice; once you trust the setup, set the
  connector's write tools to *Always allow* and let the rules do the asking.
- **Want Claude to act on its own?** Change "Never change anything on the board without my
  explicit OK" to the actions you're happy for it to take unprompted, e.g. "Add progress comments
  without asking; ask before creating, moving or closing tasks."
