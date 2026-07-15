# Granola "Everything Map" — Design

**Date:** 2026-07-15
**Status:** Approved

## Goal

Turn many Granola meeting notes into one synthesised, topic-organised mind map
("what is going on across everything"), refreshed on demand, without publishing
any meeting content to the public repo or site.

## Architecture

Two independent pieces:

### 1. App feature: local Markdown import (public, generic)

`index.html` gains two ways to load a local file into the editor:

- An **Import** button in the editor toolbar (hidden `<input type="file">`,
  accepts `.md` / `.markdown` / `.txt`).
- **Drag-and-drop** of one or more Markdown files anywhere onto the app.
  Multiple files are concatenated (blank line between) before rendering.
  A visual highlight indicates the active drop target; a toast confirms the
  import or explains rejection of non-text files.

No meeting content, folder names, or account data ships with the site. The
public site remains generic.

### 2. Claude workflow: overview generation (local, private)

A project skill (`.claude/skills/granola-overview/`, gitignored) defines a
repeatable on-demand workflow:

1. List the user's Granola folders and recent meetings (via the Granola MCP)
   and ask which to include — selection happens every run.
2. Pull the selected notes' content.
3. Synthesise **by topic/project**, not by meeting: branches are cross-meeting
   themes; under each theme gather context, decisions, and open action items.
   Leaf nodes cite source meeting title + date.
4. Write the result to `overview.md` in the project root — **gitignored,
   never committed or pushed**.
5. Load it into the app (local preview) so the map is on screen.

## Privacy invariants

- `overview.md` and `.claude/` are gitignored; meeting content never enters
  git history or the public site.
- The committed spec and app code contain no customer or account names.

## Error handling

- Import: non-text files rejected with a toast; empty file list is a no-op.
- Workflow: if the Granola MCP is unavailable, report and stop — never fall
  back to cached/stale content silently.

## Testing

- Import button and drag-drop verified in the browser (single and multiple
  files, plus a rejected binary file).
- Workflow verified end-to-end with a real run: folder selection → synthesis
  → `overview.md` → rendered map.

## Trade-offs accepted

- Refresh is manual (ask Claude); no auto-sync.
- The map is an AI synthesis, not verbatim notes; source citations on leaves
  mitigate traceability loss.
