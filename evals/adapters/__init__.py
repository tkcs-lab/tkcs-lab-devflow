"""Runtime adapters of the eval harness: each one turns a task's request into a real session of one agent runtime
and that runtime's transcript into the neutral action log (evals/harness/actions.py). The core never imports
one directly; `evals.harness.agents.adapter(name)` does."""
