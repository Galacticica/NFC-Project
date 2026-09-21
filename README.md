# NFC Project

Read, write and back up NFC tags from Windows using a PC/SC contactless
reader (developed against an **ACS ACR1552U**).

The main use is programming NTAG stickers/cards with a URL, so that tapping
one with a phone offers to open the site.

## Quick start

1. Plug the reader in. Windows installs a PC/SC driver for it automatically.
2. Double-click **`Read NFC Card.bat`** and hold a tag on the reader.

The first run offers to install `pyscard` if it is missing. Everything printed
is also saved to a `.txt` file in this folder, so the output is still there
after the window closes.

## What is here

| File | Purpose |
| --- | --- |
| `Read NFC Card.bat` | Double-click: dump a tag. Output also in `last_read.txt`. |
| `Write NFC Card.bat` | Double-click: write the default URL. Output also in `last_write.txt`. |
| `Copy NFC Card.bat` | Double-click: copy one tag onto another. Output also in `last_copy.txt`. |
| `nfc_read.py` | Identify a card and dump its memory, decoding any NDEF it finds. |
| `nfc_write.py` | Write a URL (or vCard) to an NTAG / MIFARE Ultralight tag. |
| `nfc_copy.py` | Copy the user data from one NTAG / Ultralight tag to another. |
| `nfc_backup.py` | Dump a tag to a file, restore it, or compare against a dump. |
| `_launch.bat` | Shared helper: finds Python, checks `pyscard`, runs a script. |
| `outdated/` | Unrelated older project kept in the repo; ignore it. |

## Requirements

- Windows with a PC/SC contactless reader
- Python 3 — from [python.org](https://www.python.org/downloads/), ticking
  **"Add python.exe to PATH"** during setup
- [`pyscard`](https://pypi.org/project/pyscard/), which the `.bat` files offer
  to install for you

There is no hardcoded interpreter path. `_launch.bat` looks for, in order:

1. `.venv\Scripts\python.exe` in this folder, if you made a virtualenv
2. `py -3` (the Windows Python launcher)
3. `python`, then `python3` on `PATH`

Each candidate is tested by actually running an import with it, rather than
just checking that the file exists. That matters on Windows: there is a stub
at `%LOCALAPPDATA%\Microsoft\WindowsApps\python.exe` which sits on `PATH` and
looks like a real interpreter, but only prints *"Python was not found"* unless
you installed Python from the Microsoft Store. An existence check would pick
it, and the scripts would silently never run.

To use a virtualenv instead of a system Python:

```bat
py -3 -m venv .venv
.venv\Scripts\python -m pip install pyscard
```

The `.bat` files will then pick it up on their own.

## Reading

```bat
Read NFC Card.bat
Read NFC Card.bat --watch       REM keep reading tags until you close it
Read NFC Card.bat --keys-only   REM UID and card type only, skip the dump
Read NFC Card.bat --reader PICC REM pick a reader by name substring
```

Prints the ATR, card type, UID and a page-by-page hex dump with an ASCII
column, then decodes any NDEF message (text and URI records). Understands:

- MIFARE Classic 1K/4K/Mini — tries a list of common default keys per sector
- MIFARE Ultralight / NTAG213 / NTAG215 / NTAG216 — full page dump
- ISO 14443-4 (DESFire, JCOP, phones) — NFC Forum Type 4 NDEF read

A reader normally exposes two interfaces, `... PICC 0` and `... SAM 0`. The
cards are on `PICC`, which is the default.

## Understanding the output

### What a page is

NTAG and MIFARE Ultralight tags store their memory as a flat array of
**4-byte pages**. A page is the smallest unit the tag will address: the WRITE
command writes exactly one page at a time, and READ returns four pages (16
bytes) starting wherever you ask. There is no filesystem and no byte-level
addressing — "page 6" simply means bytes 24-27 of the chip.

So the dump is the raw chip contents, four bytes per line, hex on the left and
the same bytes as ASCII on the right (a `.` wherever the byte is not a
printable character).

MIFARE Classic organises memory differently — 16-byte *blocks* grouped into
*sectors*, each sector locked behind a key — which is why those dumps say
"block" and list sectors instead.

An NTAG215 has 135 pages, 540 bytes in total. Only pages 4-129 are yours; the
rest is identity and configuration:

| Pages | Contents | Writable? |
| --- | --- | --- |
| 0-2 | UID, checksums, static lock bits | No — fixed at the factory |
| 3 | Capability container (CC) | One-time programmable |
| 4-129 | User memory, 504 bytes — your NDEF data lives here | Yes |
| 130 | Dynamic lock bits | One-way (set, never cleared) |
| 131-132 | Configuration (mirroring, password gate) | Yes |
| 133-134 | Password and acknowledge | Write-only |

### Walking through the sample dump

The header identifies the card before any memory is read:

```
ATR        : 3B 8F 80 01 80 4F 0C A0 00 00 03 06 03 00 03 00 00 00 00 68
Card type  : MIFARE Ultralight
Standard   : ISO 14443-A part 3
UID        : 04 05 A2 37 7E 61 80   (7 bytes)
```

The ATR is a synthetic one: contactless cards do not really have an ATR, so
the PC/SC layer fabricates one describing what it found. `A0 00 00 03 06` is
the PC/SC Workgroup's registered identifier, the `03` after it means ISO
14443-A part 3, and `00 03` is the card-type code for MIFARE Ultralight.

Note that the *protocol* only says "MIFARE Ultralight" — that family shares a
command set. The exact model is worked out afterwards from the capability
container, which is why the next line says NTAG215.

**Pages 0-2 — identity.** The 7-byte UID is split across pages 0 and 1, with
checksum bytes wedged in:

```
  page   0 | 04 05 A2 2B | ...+      <- UID bytes 0-2, then BCC0
  page   1 | 37 7E 61 80 | 7~a.      <- UID bytes 3-6
  page   2 | A8 48 00 00 | .H..      <- BCC1, internal, 2 static lock bytes
```

`BCC0` and `BCC1` are XOR checksums the reader uses to catch garbled
transmissions. They are derived, not stored data — BCC0 is `0x88` XOR the
first three UID bytes, BCC1 is the XOR of the last four:

```
0x88 ^ 04 ^ 05 ^ A2 = 2B    matches BCC0
  37 ^ 7E ^ 61 ^ 80 = A8    matches BCC1
```

The lock bytes are `00 00`, so nothing on this tag has been locked read-only.

**Page 3 — the capability container.** Four bytes that tell any phone how to
treat the tag:

```
  page   3 | E1 10 3E 00 |
             |  |  |  +-- 00 = read/write (non-zero would mean read-only)
             |  |  +----- 3E x 8 = 496 bytes usable for an NDEF message
             |  +-------- 10 = NDEF mapping version 1.0
             +----------- E1 = magic byte: this tag is NDEF formatted
```

That `3E` is what identifies the chip. The script looks it up in `NTAG_SIZES`
in [`nfc_read.py`](nfc_read.py) — `0x3E` means NTAG215, 135 pages — and that
is also how it knows where to stop dumping. Read past the last page and these
tags silently wrap back to page 0, so a dump that did not know the real size
would end with a phantom copy of page 0.

Page 3 is one-time programmable: bits can be set but never cleared, which is
why writing to an unformatted tag is a one-way door.

**Pages 4-15 — the actual data.** User memory does not start with the URL
directly. It starts with a TLV (tag-length-value) wrapper:

```
  page   4 | 03 2C D1 01 |
             |  |  +-- NDEF record starts here
             |  +----- 2C = 44 bytes long
             +-------- 03 = "an NDEF message follows"
```

Inside that, the 44 bytes are one NDEF record:

| Bytes | Value | Meaning |
| --- | --- | --- |
| `D1` | flags + TNF | first and last record of the message, short form, type is an NFC Forum well-known one (TNF `0x01`) |
| `01` | type length | the type name is 1 byte |
| `28` | payload length | 40 bytes |
| `55` | type | `U`, i.e. a URI record |
| `02` | URI prefix | `https://www.` |
| 39 bytes | text | `reaganzierke.com/development-portfolio/` |

Which is why pages 6 onward read as plain text in the ASCII column:

```
  page   6 | 65 61 67 61 | eaga
  page   7 | 6E 7A 69 65 | nzie
  page   8 | 72 6B 65 2E | rke.
  page   9 | 63 6F 6D 2F | com/
```

The prefix byte is the reason `https://www.` never appears in the dump. Only
39 characters are stored for a 51-character URL, because that one `02` byte
stands in for the scheme. On a tag this large it hardly matters; on a 48-byte
NTAG213 it is the difference between fitting and not.

Page 15 closes it out:

```
  page  15 | 6F 2F FE 00 | o/..
                    +-- FE = terminator: nothing meaningful after this
```

So the whole message occupies 47 of the 504 available bytes, and everything
from page 16 to page 129 is untouched `00` — blank space, not a problem.

**Pages 130-134 — configuration.** The tail is not data:

```
  page 130 | 00 00 00 BD |   dynamic lock bits 00 00 00 = nothing locked
  page 131 | 04 00 00 FF |   last byte FF = password protection disabled
  page 132 | 00 05 00 00 |   access config, factory default
  page 133 | 00 00 00 00 |   password  - always reads back as zeros
  page 134 | 00 00 00 00 |   ack value - always reads back as zeros
```

Pages 133-134 are write-only by design: the tag will accept a password but
never hand it back, so zeros here do **not** mean no password is set. The
`FF` on page 131 is the reliable indicator — it is the page number from which
protection would begin, and `FF` is past the end of memory, so nothing is
protected.

The summary block at the bottom is just these same bytes restated in plain
language, followed by the decoded URL.

### The `[waiting]` lines

```
  [waiting] Unable to connect: The smart card has been removed ... (0x80100069)
  [waiting] Failed to transmit with protocol T1. No media in drive. (0x00000458)
```

Both mean the same thing: no tag is on the reader right now. The first is
normal and expected before you present a card — the script polls, and prints
the reason once rather than repeating it every quarter second.

Seeing one *after* the dump has started, as in the sample above, means the tag
left the field partway through. That is why the sample shows the header twice:
the first attempt got as far as `-- NTAG215 pages --` before losing contact,
and the script started over when the tag came back. The second attempt ran to
completion. Nothing is wrong with the tag; it just needs to stay put until the
dump finishes.

## Writing

Targets NTAG / MIFARE Ultralight tags. The default URL is set by `DEFAULT_URL`
near the top of `nfc_write.py`.

```bat
Write NFC Card.bat
Write NFC Card.bat https://example.com
Write NFC Card.bat --verify-only                  REM read back the URL, write nothing
Write NFC Card.bat --uid 0405A2377E6180           REM only write if the UID matches
Write NFC Card.bat --vcard --name "Jane Doe" --phone +1555... --email a@b.com
```

Notes:

- The URL is stored as an NDEF URI record. A common scheme prefix such as
  `https://www.` is replaced by a single byte, so it does not eat into the
  tag's limited memory.
- If a tag holds unrecognised data, the write **stops** and shows what is
  there rather than overwriting it. Back it up first, then re-run with
  `--force` if you really mean it.
- `--vcard` is Android-only; iPhone ignores vCard records on tags.

## Copying

```bat
Copy NFC Card.bat          REM tap the source, then the target
Copy NFC Card.bat --yes    REM do not ask before overwriting the target
```

Tap the card to copy **from**, take it off, then tap the card to copy **to**.
Both are saved as `backup_<UID>.txt` before anything is written, and the
target is read back afterwards to check every page.

- Only user memory (page 4 onward) is copied. The UID cannot be copied — it
  is fixed at the factory — so the copy keeps its own UID.
- Lock and configuration pages are never copied, so a copy can never lock
  or password-protect the target.
- If the target is blank, it is NDEF-formatted using its *own* size, not the
  source's. A larger source can be copied to a smaller tag as long as the
  data actually on it fits.
- Pages on the target past the end of the copied data are cleared.
- To undo: `py -3 nfc_backup.py --restore backup_<target UID>.txt`

## Backing up

Take a backup before writing to a card you care about.

```bat
py -3 nfc_backup.py                    REM dump to backup_<UID>.txt
py -3 nfc_backup.py --compare FILE     REM show differences, change nothing
py -3 nfc_backup.py --restore FILE     REM write a dump back to the tag
```

A restore can only rewrite page 4 onward, which is where user data lives.
Pages 0-2 hold the UID and are permanently read-only; page 3 is the capability
container and is one-time programmable — bits set there can never be cleared.

## Troubleshooting

**"Python was not found; run without arguments to install from the Microsoft
Store"** — `PATH` is reaching the Store stub described above and no real Python
is installed. Install Python 3 from python.org with "Add python.exe to PATH"
ticked.

**"No reader matched ..."** — the script lists the readers it can see and falls
back to the first one. If the list is empty, the reader is not plugged in or
Windows has not finished installing its driver.

**`[waiting] ... The smart card has been removed (0x80100069)`** — normal.
It means no tag is on the reader yet; present one.

**The write stops with "This looks like an existing card"** — deliberate. See
the writing notes above.
