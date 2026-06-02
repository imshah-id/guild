"""guild: run your installed AI coding CLIs as a coordinated team.

One master command. You give it a goal; a planner agent decomposes it, hands the work to a
coder agent, a different agent reviews every change (cross-review), tests run, and fix loops
close the gaps, pausing only at the gates you choose. No model APIs and no cloud: the agents
are plain CLIs invoked as subprocesses, and state flows through files. Pure Python stdlib.
"""
from __future__ import annotations

__version__ = "0.1.0"
