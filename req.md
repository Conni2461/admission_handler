# Requirements Analysis

- Dynamic discovery of hosts: It should be able to dynamically open new
  entrances when the queues in front of the current set of entrances too long
  is. This allows us to move the load from multiple active hosts to the new
  host.
- Fault Tolerance: When a server in the server group fails, then this doesnt
  effect the performance/operation of the whole system. It continues to run as
  it is. If a checkin station fails, we need to make sure that the checkin has
  a backup checkin station which can be used until the first one is running
  again.
- Voting: New devices need to authenticate by the leader of the server group.
- Ordered Reliable Multicast: Its required that the multicast is order because
  we need to make sure that the people are allowed to enter in the order they
  checked in. So if multiple person check in the same timeframe and we have
  only one spot left, we can reqect the last personthat has checked in
