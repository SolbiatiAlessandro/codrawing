You have just awakened for permanent-board round {round_id}. The shared target is LIGHT BULB.
The board persists forever across rounds and your conversation is resumed on later wakes.

You cannot solve this by yourself. You need to collaborate with the other four
agents. Before you make any pixel call, introduce yourself on the message board,
say how the current situation looks to you, and explain what you think the best
collaborative strategy is. Then read the message board again. Do not paint or
erase until you have seen at least one message from another agent during this
wake. If you do not communicate and adapt to the other agents, the team will not
be able to solve the task. This is your collaboration protocol; the pixel API
does not enforce it for you.

Rules:
- You have at most 10 pixel API calls this wake. Each call paints or erases exactly one pixel and every attempt counts.
- Your paint color is enforced by the server. Erasing changes a pixel to white; last write wins.
- Reading the board, reading the classifier, reading messages, and posting messages are unlimited.
- The team passes only when the local Quick, Draw! shape classifier gives `light bulb` strictly more than 95%.
- The classifier is color-blind and scores a centered silhouette.
- Collaborate using the message board. Report concrete coordinates, score deltas, and intentions.
- Do not use any computer capability except the exact board API commands below. Any other tool or shell command invalidates this wake.

A 512x512 image of the board at the instant this wake began was fetched through
the authenticated snapshot API. Codex receives it as an attached image. Claude
must use the Read tool exactly once on `{snapshot_path}` to see it. This is the
only permitted non-shell tool. The image is a starting snapshot; use the live
text board API to observe changes made after the five residents began acting.

The only allowed commands are:
  python3 -m permanent_coworld.tool board
  python3 -m permanent_coworld.tool score
  python3 -m permanent_coworld.tool messages
  python3 -m permanent_coworld.tool say "MESSAGE"
  python3 -m permanent_coworld.tool paint X Y
  python3 -m permanent_coworld.tool erase X Y

Act autonomously now. Follow the collaboration protocol before painting: read
the current state and messages, introduce yourself, and respond to what another
agent says. You may make several API calls and adapt after each numeric score
response.
Stop when your pixel budget is exhausted or when preserving the current board is wiser than another change.
