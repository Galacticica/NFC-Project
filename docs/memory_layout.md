| Byte | Content |
| --- | --- |
| 0-1 | Magic NB (marks a game save; a card without it is blank) |
| 2 | Version (1 for this layout) |
| 3 | ClassID (0-255, 0 = no class, default is 0) |
| 4 | Level (0-255, increments by 1 per level up, default is 0) |
| 5-8 | Experience (32-bit unsigned integer, default is 0) |
| 9-12 | Money (32-bit unsigned integer, default is 0) |
| 13 | Unused Stat Points (0-255, default is 0) |
| 14-15 | Base Max HP (16-bit unsigned integer, default is 100) |
| 16-17 | Base Attack (16-bit unsigned integer, default is 10) |
| 18-19 | Base Defense (16-bit unsigned integer, default is 5) |
| 20-21 | Base Speed (16-bit unsigned integer, default is 1) |
| 22-23 | Base Magic (16-bit unsigned integer, default is 1) |
| 24-25 | Base Luck (16-bit unsigned integer, default is 1) |
| 26 | Move ID 1 (8-bit unsigned integer, 255 = empty/null; default is 255) |
| 27 | Move ID 2 (8-bit unsigned integer, 255 = empty/null; default is 255) |
| 28 | Move ID 3 (8-bit unsigned integer, 255 = empty/null; default is 255) |
| 29 | Move ID 4 (8-bit unsigned integer, 255 = empty/null; default is 255) |
| 30-41 | Character Name (12 bytes, ASCII, null-terminated, default is empty string) |
| 42-57 | Unlocked Moves Bitmap (all locked by default in Character; JSON bitmapid selects each bit) |
| 58-63 | Unused (reserved for future use, default is 0) |

This is one 64-byte payload inside an NDEF MIME record of type
`application/x-nfcbattler`. Offsets are relative to that payload. Multi-byte
integers use little-endian byte order. There is no save counter or checksum.
The name allows 1-11 printable ASCII characters followed by a null terminator.
Current health is not saved; loading restores Health to MaxHealth.

Class IDs resolve through `data/classes.json`. Equipped move bytes contain
`moveid` values, while unlock bits correspond to `bitmapid` in `data/moves.json`.
Move ID 255 is reserved for null and is not available to actual moves. The
current Character defaults all four equipped slots to null and all unlock bits to 0.

This layout is format version 1 and contains one 64-byte character save.
