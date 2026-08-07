# Codrawing player protocol

Each player container receives `COWORLD_PLAYER_WS_URL` and connects to it. The server first sends a welcome frame with the player's zero-based `slot`.

At the start of every turn the server sends an `observation`. It contains the shared target, current canvas, player names, accepted-pixel counts, and the latest public messages:

```json
{
  "type": "observation",
  "slot": 0,
  "target": "cat",
  "turn": 3,
  "max_turns": 50,
  "width": 24,
  "height": 24,
  "canvas": ["#FFFFFF", "#111827"],
  "owners": [-1, 2],
  "player_names": ["Artist 1", "Artist 2", "Artist 3", "Artist 4", "Artist 5"],
  "accepted_pixels": [3, 3, 3, 3, 2],
  "recent_messages": []
}
```

The player replies once for that turn with one public message and one pixel:

```json
{
  "turn": 3,
  "message": "I will outline the left ear.",
  "paint": {"x": 7, "y": 5, "color": "#AAB4C4"}
}
```

Messages may be empty and have a maximum length of 240 characters. Colors use six-digit hex form. Invalid or late actions are ignored. Actions resolve at the same time; when two or more players choose the same pixel, every write to that pixel is dropped. A slow or disconnected player does not block the episode beyond `action_timeout_seconds`.

The final server frame has `type: "final"`; the player must then exit.
