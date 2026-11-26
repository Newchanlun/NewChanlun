module

public section

theorem t : True := aux
where aux : True := by
  trivial

theorem t2 : True := aux2
where
  aux2 : True := by
    trivial
