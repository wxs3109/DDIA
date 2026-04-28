# Leader-Follower (Single-Leader) Replication
# Reference: DDIA ch6, sec_replication_leaders
#
# Core ideas to implement:
# - leader accepts writes, appends to replication log
# - followers apply log in order
# - replication lag, read-your-writes, monotonic reads

class Leader:
    pass  # TODO

class Follower:
    pass  # TODO
