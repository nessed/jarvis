# Blockers

One file per reproducible failure that survived two attempts. Naming:
`<slug>.md`. Each file records the exact reproduction command, the exact
failure output, everything already tried, and the single action the user would
have to take to unblock it.

The point is to stop paying for the same failure twice. An agent that finds a
matching file here does not retry the thing — it moves to other work and
raises the blocker once in the next batched handoff.
