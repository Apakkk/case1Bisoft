"""Pure carrier-selection rules: no database, HTTP or Jev. Everything here is deterministic.

Flow (orchestrated by QuoteService):
    filter_carriers()  -> hard constraints, every failure collected as a reason
    with_hq_distances() -> service supplies HQ -> origin distances (I/O happens outside)
    rank()             -> lexicographic ordering from rules.yaml
    explain()          -> Turkish explanation from the trace, by template
"""
