# ToDos

###### _from notes_2021_21_02.txt_

- [x] Project Structure
- [x] Dynamic Discovery
    - [x] Hosts
        - [x] Group View etc.
    - [ ] Clients
- [ ] (Abstract) Client Logic

- [x] Build ring
    - [x] Leader Election (Ring-Election?)

- [x] Multicast
    - [x] Infrastructure
    - [x] Reliable
    - [x] Ordered
    - [ ] what happens if a server is missing a message (nAck) from another server that is no longer online/ in the group view ?
    - [ ] "_handle" method in listeners is not using tcp

- [ ] Failure-Model
    - [ ] Clients
    - [ ] Hosts
        - [ ] Leader
        - [x] heartbeats
        - [ ] handle when a server is offline but then comes online again (also leader) how to recognize this, what to do.

- [ ] Optional
    - [ ] Visualization
    - [ ] Client UI
    - [ ] Monitoring