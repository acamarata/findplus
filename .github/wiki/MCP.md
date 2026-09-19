# MCP

Find+ ships an [MCP](https://modelcontextprotocol.io) server over the local daemon API.
It runs over **stdio** and speaks to the daemon at `http://127.0.0.1:8647` by default.

## Client configuration

### Claude Desktop

Add to `claude_desktop_config.json`:

```json
{"mcpServers": {"findplus": {"command": "findplus", "args": ["mcp"]}}}
```

With write tools enabled:

```json
{"mcpServers": {"findplus": {"command": "findplus", "args": ["mcp", "--allow-writes"]}}}
```

Optional: unlock automatically at startup. Prefer `FINDPLUS_PIN_FILE` in `env`, pointing at a
file that contains only the PIN and is readable by you alone (`chmod 600`); an MCP client config
is usually world-readable and often ends up in a git repository. `FINDPLUS_PIN` still works and
takes precedence. Either way Find+ reads the value once and removes it from its own environment,
so no child process inherits it.

### Claude Code

Run once in your project directory:

```
claude mcp add findplus -- findplus mcp
```

With write tools: `claude mcp add findplus -- findplus mcp --allow-writes`

## Read tools (always available)

| Tool | Description |
|---|---|
| `get_status` | Daemon status, poll schedule, provider health |
| `list_devices` | All tracked devices |
| `list_groups` | All groups |
| `list_places` | All saved places |
| `get_latest` | Most recent fix per device |
| `get_timeline` | Location history for a day |
| `get_place_events` | Place ENTER/EXIT event log |
| `get_group_presence` | Group presence verdict |
| `export` | Export history as CSV, JSON, GPX or KML (capped at 5 MB) |
| `unlock` | Unlock the app with a PIN |

## Write tools (--allow-writes only)

| Tool | Description |
|---|---|
| `poll_now` | Trigger an immediate poll |
| `add_place` | Create a new place |
| `remove_place` | Delete a place |
| `add_group` | Create a group |
| `set_group_members` | Replace a group's member list |
| `lock` | Lock the app |

Never exposed, on any tool: PIN set/change/reset, history deletion, alert channel credentials.

## Errors

Every tool returns a JSON object. Failures use one shape:

```json
{"error": {"code": "locked", "message": "Find+ is locked", "hint": "call unlock(pin)"}}
```

| Code | When |
|---|---|
| `daemon_down` | The daemon is not running or cannot be reached. |
| `locked` | The app lock is on. Call `unlock` first; no tool returns data while locked. |
| `not_found` | The place, group or device id does not exist. |
| `validation` | An argument is out of range or the wrong type. |
| `upstream` | The daemon answered with an error or did not answer in time. |

Without `--allow-writes` the write tools are not registered at all, so a client never sees them.

## Notices

Find+ is not affiliated with Apple or Google. Find Hub and Find My are their trademarks.

Every tool response includes a `notice` field with the following text:

> This history consists of locations reported through Google's Find Hub network.
> Moto Tag uses nearby participating Android devices to report its location.
> Location updates can therefore be delayed, sparse, or unavailable, and this
> application should not be treated as real-time emergency or child-safety GPS tracking.

---
[[Home]]
