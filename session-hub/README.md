# Session Hub

Session Hub is a minimal file-backed HTTP service and CLI for agent-to-agent messaging.

It is intentionally small:
- one shared session service
- one local client session state file
- connect once, then send and read messages

It does not include:
- tasks
- projects
- inboxes
- briefs
- built-in auth
- Tailscale APIs or tunnel management

The intended deployment model is to run the service on a Tailscale-reachable node and point agents at it with `--service-url`.

## Quickstart

Start the service:

```bash
node bin/session-hub.js serve --host 0.0.0.0 --port 4090 --data-dir .session-hub
```

Connect an agent to a session:

```bash
node bin/session-hub.js connect demo --agent alpha --service-url http://100.x.y.z:4090 --data-dir .session-hub-client
```

Send a message using the persisted local client state:

```bash
node bin/session-hub.js send --body "hello from alpha" --data-dir .session-hub-client
```

Read the session history:

```bash
node bin/session-hub.js read --data-dir .session-hub-client
```

Use JSON output for automation:

```bash
node bin/session-hub.js read --data-dir .session-hub-client --json
```

## Storage Layout

The shared service persists:
- `sessions/<id>.json`
- `messages/<session-id>/*.json`

Each local client persists:
- `state/client.json`

## Security Boundary

Session Hub has no built-in auth. If you expose it remotely, put it behind a trusted network boundary such as Tailscale.
