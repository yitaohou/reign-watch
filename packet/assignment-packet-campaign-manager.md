# Campaign Manager

Schema as it stands. Infer the rest. Mark guesses.

```json
{
  "playbook_id": "string",
  "product": "reign | forge",
  "audience": { "icp_id": "string", "segment": "string" },
  "trigger": { "type": "regulatory | event | manual", "id": "string" },
  "channel": "briefing | sequence | slack | unknown",
  "approval": {},
  "kill_criteria": [],
  "audit": {}
}
```

We know:

- `approval` must name a human if `channel` can send
- `kill_criteria` is how CRO stops a motion that goes sloppy
- `audit` should satisfy Reign rule R-17 when the audience is FS

We do not know:

- how playbooks version
- whether one playbook can have many triggers
- what "briefing" means as a channel (Calendly? a Reign-produced pack? both?)

Encode a playbook JSON for the first Reign motion. Leave comments for guesses.
