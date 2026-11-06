| Byte | Content |
| --- | --- |
| 0-1 | Magic NB (marks a game save; a card without it is blank) |
| 2 | Version (1, if ever changed shows outdated save exists) |
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
| 26 | Move ID 1 (8-bit unsigned integer, default is 0) |
| 27 | Move ID 2 (8-bit unsigned integer, default is 0) |
| 28 | Move ID 3 (8-bit unsigned integer, default is 0) |
| 29 | Move ID 4 (8-bit unsigned integer, default is 0) |
| 30-45 | Unlocked Moves Bitmap (each bit represents a move, 0 = locked, 1 = unlocked, default is 0) |
| 46-57 | Character Name (12 bytes, ASCII, null-terminated, default is empty string) |
| 58-63 | Unused (reserved for future use, default is 0) |