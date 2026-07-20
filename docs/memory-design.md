# Conversation memory design

The memory implementation has three independent layers plus explicit document state.

## Layers

1. **Working memory:** authoritative messages are stored in PostgreSQL. The loader keeps
   a complete recent suffix within 16 turns and 12,000 exact Nemotron tokens; it never
   cuts a message in half.
2. **Rolling summary:** when history exceeds the recent window, a schema-checked summary
   records goal, facts, decisions, open questions, constraints, referenced documents and
   working state. Each version stores the covered source message IDs.
3. **Long-term semantic memory:** only explicit preference/fact/decision/project-state/
   todo statements are captured. Items are embedded with the selected 300M model and
   retrieved with local semantic plus lexical scoring. Automatic inference is forbidden.
4. **Conversation state:** active document IDs, current task and response depth are stored
   server-side so a follow-up can refer to an uploaded file without reattaching it.

All repositories require trusted tenant and user scope. Tests cover exact token suffixes,
summary drift, cross-user isolation, explicit capture and active-document reuse.

## User controls

- `GET /api/v1/memory` lists the current user's active items.
- `DELETE /api/v1/memory/{item_id}` deletes one owned item.
- `DELETE /api/v1/memory` clears the user's items.
- `PUT /api/v1/conversations/{conversation_id}/memory` enables/disables persistent memory.
- `DELETE /api/v1/conversations/{conversation_id}/memory` resets that conversation memory.

Conversation messages persist even when enhanced memory is disabled. This fixes the old
behavior where the feature flag accidentally disabled basic chat history as well.

## Schema and rollout

Migrations `0008_chat_memory_contract`, `0010_conversation_memory` and the forward repair
`0013_conversation_documents` are additive. The last migration repairs environments whose
Alembic revision had advanced while `app.conversation_documents` was absent.

Rollback flags are `ENABLE_NEW_MEMORY`, `ENABLE_ROLLING_SUMMARY` and
`ENABLE_LONG_TERM_MEMORY`. Disabling enrichment does not delete stored user data; explicit
delete/reset endpoints remain authoritative.
