module

public import Chan.Defs.Fixture

public section

theorem registered (r : Reviewed) : r.inRange = decide (r.raw.points > 0) := raw_to_criterion r
