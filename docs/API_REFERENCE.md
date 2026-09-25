# Otomater AI - REST API Reference

Base path: `/otomater_ai/api`

## Authentication

Every endpoint needs an API key, generated at **Otomater AI > API Keys**.
Pass it either as `"api_key"` in the JSON body, or as an `X-Api-Key`
header. A key runs with exactly that key's user's Odoo permissions -
never more.

OAuth2/JWT is not implemented as a full authorization server here. If you
have an existing identity provider, `_authenticate()` in
`controllers/main.py` is the one place to change - resolve the incoming
token to a `res.users` record there, and every endpoint below keeps
working unchanged.

All responses are JSON with at least `{"ok": true|false}`. Failures also
include `"error"` and use a non-2xx HTTP status.

---

## POST /chat

```json
{"api_key": "...", "message": "How many leave requests are pending?", "conversation_id": null}
```

`conversation_id` is optional - omit it (or pass `null`) to use/create
your one open conversation. Response:

```json
{
  "ok": true,
  "conversation_id": 12,
  "message": {
    "id": 45, "role": "assistant", "content": "Count: 3",
    "message_type": "text", "pending_action_id": false,
    "agent": "Leave Agent", "status": "success", "error_message": false
  }
}
```

## POST /search

Shortcut for the `search_records` tool.

```json
{"api_key": "...", "model": "res.partner", "domain": [["is_company", "=", true]], "fields": ["name", "email"], "limit": 20}
```

## POST /knowledge_search

```json
{"api_key": "...", "query": "probation leave policy", "limit": 5}
```

## POST /execute

Generic tool call. Read tools (`search_records`, `count_records`,
`read_record`, `search_knowledge`, `open_form`, `download_report`) run
immediately. Destructive tools (`create_record`, `update_record`,
`delete_record`, `call_method`, `execute_server_action`) create a pending
action instead of running.

```json
{"api_key": "...", "tool_name": "create_record", "params": {"model_name": "res.partner", "values": {"name": "Rahul Menon"}}}
```

Destructive response:

```json
{"ok": true, "pending_action_id": 7, "state": "pending", "description": "...", "message": "This action requires confirmation - POST to /otomater_ai/api/confirm with this pending_action_id."}
```

## POST /confirm

```json
{"api_key": "...", "pending_action_id": 7, "approve": true}
```

`approve: false` rejects instead. Response includes the resulting
`state` (`executed`/`error`/`rejected`) and the reply text.

## GET /reports

```
GET /otomater_ai/api/reports?api_key=...&model=res.partner
```

Lists `ir.actions.report` records visible to the caller (optionally
filtered by `model`).

---

## Error shape

```json
{"ok": false, "error": "Invalid or inactive API key"}
```

Common status codes: `400` bad request, `401` missing/invalid API key,
`403` pending action belongs to a different user, `404` not found, `422`
the tool call itself failed (e.g. an ACL/validation error from Odoo).
