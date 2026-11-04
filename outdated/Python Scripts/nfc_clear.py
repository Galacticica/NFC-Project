#!/usr/bin/env python3
"""
Clear an NFC tag so it reads as blank.

    python nfc_clear.py          # tap the tag, confirm, clear
    python nfc_clear.py --yes    # skip the "erase this tag?" question

Targets MIFARE Ultralight / NTAG tags (NTAG213/215/216). User memory - page 4
up to the end of the user area - is wiped:

  - an NDEF-formatted tag gets an empty NDEF message (03 00 FE) on page 4 and
    zeros after it. That is exactly how a new blank tag reads, so phones see
    it as empty and writable;
  - an unformatted tag just gets zeros.

What cannot be cleared, because the chip does not allow it:

  - pages 0-2 hold the UID, burned in at the factory;
  - page 3, the capability container, is one-time programmable, so a
    formatted tag stays formatted. That is harmless - formatted and empty is
    the normal blank state;
  - lock bits are one-way, so a page locked read-only stays that way;
  - a password protected tag cannot even be read without the password, and
    is refused rather than half-cleared.

The tag is backed up to backup_<UID>.txt before anything is written, so a
clear can be undone with:  python nfc_backup.py --restore FILE

Bank cards, phones and MIFARE Classic cards are not storage tags and are
never written to.
"""

import argparse
import os
import sys
import time
import traceback

from nfc_backup import Tee, banner, hexs, read_all_pages, save_dump
from nfc_copy import (CC_PAGE, FIRST_DATA_PAGE, confirm, describe, pick_reader,
                      read_tag, uid_hex, wait_for_tag)

HERE = os.path.dirname(os.path.abspath(__file__))
LOG_PATH = os.path.join(HERE, "last_clear.txt")

# NDEF TLV with length 0, then the terminator TLV: "formatted, but empty".
EMPTY_NDEF = [0x03, 0x00, 0xFE, 0x00]

# How many of the tag's leading data pages to show before erasing, so the
# card can be recognised.
PREVIEW_PAGES = 8


def printable(page):
    return "".join(chr(b) if 32 <= b < 127 else "." for b in page)


def lock_bits_set(pages, user_end):
    """True if any user page may be locked read-only.

    Static lock bytes (page 2, bytes 2-3) cover pages 4-15; the low nibble of
    byte 2 only guards the lock bits themselves and the CC, so it is ignored.
    Larger tags also have dynamic lock bytes on the page straight after user
    memory - except the 20-page MF0UL11, which has none."""
    static = pages[2][2] & 0xF0 or pages[2][3]
    dynamic = len(pages) != 20 and any(pages[user_end][0:3])
    return bool(static or dynamic)


def main():
    ap = argparse.ArgumentParser(description="Clear an NFC tag so it reads as blank.")
    ap.add_argument("--yes", action="store_true",
                    help="do not ask before erasing the tag")
    ap.add_argument("--reader", default="PICC",
                    help="pick a reader by name substring (default: PICC)")
    args = ap.parse_args()

    reader = pick_reader(args.reader)
    print("Using reader : %s\n" % reader)

    card, uid = wait_for_tag(reader, "Tap the card to CLEAR...")
    try:
        pages, model = read_tag(card, "NFC")
        if not pages:
            print("\n  Only NTAG / MIFARE Ultralight tags can be cleared. Bank cards,"
                  "\n  phones and MIFARE Classic cards are left alone.")
            return

        _, user_end, _ = model
        print()
        describe("Tag", uid, pages, model)

        if any(page is None for page in pages[:user_end + 1]):
            banner("TAG PARTLY UNREADABLE",
                   "It is probably password protected. Nothing written.")
            return

        cc = pages[CC_PAGE]
        formatted = cc[0] == 0xE1
        if formatted and cc[3] != 0x00:
            banner("TAG IS READ-ONLY", "Its capability container marks it locked.")
            return

        user = pages[FIRST_DATA_PAGE:user_end]
        wanted = [[0, 0, 0, 0] for _ in user]
        if formatted:
            wanted[0] = list(EMPTY_NDEF)
        changes = [(FIRST_DATA_PAGE + i, page) for i, page in enumerate(wanted)
                   if list(user[i]) != page]

        if not changes:
            banner("TAG IS ALREADY BLANK", "Nothing to write.")
            return

        used = len(user)
        while used and not any(user[used - 1]):
            used -= 1
        print("         %d of %d user pages hold data:\n" % (used, len(user)))
        for i in range(min(used, PREVIEW_PAGES)):
            print("  page %3d | %s | %s"
                  % (FIRST_DATA_PAGE + i, hexs(user[i]), printable(user[i])))
        if used > PREVIEW_PAGES:
            print("  ... and %d more" % (used - PREVIEW_PAGES))

        if lock_bits_set(pages, user_end):
            print("\n  Warning: this tag has lock bits set. Locked pages cannot be"
                  "\n  erased and will be reported after the write.")

        backup = os.path.join(HERE, "backup_%s.txt" % uid_hex(uid))
        save_dump(backup, uid, pages)
        print("\n  Backed up to %s" % os.path.basename(backup))

        print("\nAbout to erase %d page(s)%s."
              % (len(changes), ", leaving it NDEF formatted and empty" if formatted else ""))
        if not args.yes and not confirm("Erase this tag?"):
            print("\nCancelled - nothing written.")
            return

        # The tag may have moved while the question was on screen.
        card.reconnect()
        if list(card.uid() or []) != uid:
            banner("CARD CHANGED", "A different tag is on the reader now.")
            return

        # Page 4 goes first: once it holds the empty NDEF message, the tag
        # already reads as blank even if the rest is interrupted.
        print("\nErasing...")
        failed = []
        for page, data in changes:
            if card.write_page(page, data):
                print("  page %3d <- %s" % (page, hexs(data)))
            else:
                print("  page %3d -- WRITE FAILED" % page)
                failed.append(page)
            # Back-to-back writes make the reader reset the card.
            time.sleep(0.05)

        print("\nVerifying by reading the tag back...")
        try:
            card.reconnect()
        except Exception:
            pass
        after = read_all_pages(card, user_end)
        wrong = [FIRST_DATA_PAGE + i for i, page in enumerate(wanted)
                 if after[FIRST_DATA_PAGE + i] is None
                 or list(after[FIRST_DATA_PAGE + i]) != page]

        if failed or wrong:
            banner("CLEAR INCOMPLETE",
                   "Pages %s still hold data."
                   % ", ".join(str(p) for p in sorted(set(failed + wrong))))
        else:
            banner("TAG CLEARED", "%d page(s) erased on %s." % (len(changes), uid_hex(uid)))
        print("\n  Undo with:  python nfc_backup.py --restore \"%s\""
              % os.path.basename(backup))
    finally:
        card.close()


if __name__ == "__main__":
    sys.stdout = Tee(sys.stdout, LOG_PATH)
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        print("\n*** The program hit an error ***\n")
        traceback.print_exc(file=sys.stdout)
    finally:
        print("\nThis output was also saved to:\n  %s" % LOG_PATH)
        if sys.stdin is not None and sys.stdin.isatty():
            try:
                input("\nPress Enter to close...")
            except (EOFError, KeyboardInterrupt):
                pass
