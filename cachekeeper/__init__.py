"""cachekeeper: keep Claude Code's prompt cache from being thrown away by accident.

Two parts, both local and dependency-free:

* a PreModelSwitch/PostModelSwitch hook pair that asks before a model switch
  forfeits a warm cache, using the cost Claude Code itself computes;
* ``cachekeeper audit``, which reads your transcripts and attributes every
  cache rebuild to its cause (model switch, idle expiry, effort change,
  compaction, session start).
"""

__version__ = "0.2.0"
