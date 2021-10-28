---
header-includes: |
    \usepackage{fancyhdr}
    \pagestyle{fancy}
    \fancyhf{}
    \fancyhead[LE,LO]{Proposal}
    \fancyhead[RE,RO]{Group 18}
    \fancyfoot[LE,RO]{\thepage}
---

# Distributed Admission Handler


We suggest implementing an access-system for lecture rooms, concerts and
similar venues with a limit on participants.

Access is checked by security with smartphones in front of each door, while
each smartphone displays the current number of available spots. The requests
from each entrance are load balanced across a small cluster of servers that
keep track of the available spots.

In case of outages, connection loss etc., data is synced between servers/to new
clients.
