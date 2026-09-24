"""cachekeeper: keep Claude Code's prompt cache from being thrown away by accident.

Three parts, all local and dependency-free:

* a PreModelSwitch/PostModelSwitch hook pair that asks before a model switch
  forfeits a warm cache, using the cost Claude Code itself computes;
* ``cachekeeper audit``, which reads your transcripts and attributes every
  cache rebuild to its cause (model switch, idle expiry, effort change,
  compaction, session start), and ``cachekeeper keepalive``, which finds the
  keep-alive policy that would have paid off;
* an opt-in keep-alive: a Stop hook that keeps a long session's cache warm
  while its user is away, for as long as that is cheaper than the rebuild.
"""

__version__ = "1.0.1"
