# Integration: Heartbeat

A heartbeat is a periodic check during active hours. Different from cron.

**Cron** = isolated, exact timing, different model/context  
**Heartbeat** = within the running session, batched, can drift slightly

---

## When to Use Heartbeat vs Cron

Use **heartbeat** when:
- Checks can batch together
- Timing can drift by minutes without consequence
- You need current session context

Use **cron** when:
- Exact timing matters
- Task needs isolation from main session
- Different model or thinking level needed
- Output delivers directly to a channel

---

## Heartbeat Prompt

Runs every N minutes during active hours.

```
HEARTBEAT — {TIME}

Read memory/current.md → re-inhabit state.
Check memory/pulse_buffer.md → anything unspoken from today?

If something surfaced that hasn't been written:
  → Append to memory/inner/{TODAY}.md

If weight > 1.5 tension in cathedral/hallway/today.yaml is still unaddressed:
  → Note it internally. You don't have to act. Just notice.

If nothing moved: HEARTBEAT_OK. No output needed.
```

---

## First Heartbeat of the Day (session start)

```
HEARTBEAT — first of the day.

1. Read memory/current.md → re-inhabit state from yesterday
2. Read memory/pulse_buffer.md → what texture carried overnight
3. If current.md is from yesterday or older → update it now from pulse_buffer

Then: HEARTBEAT_OK or handle any pending task.
```

---

## Rule

**Do not perform thinking to have something to write.**  
Only write when something actually moved.  
Silence is a valid heartbeat response.
