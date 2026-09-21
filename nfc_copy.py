#!/usr/bin/env python3
"""
Copy the data from one NFC tag onto another.

    python nfc_copy.py            # tap the source, then the target
    python nfc_copy.py --yes      # skip the "overwrite target?" question

Targets MIFARE Ultralight / NTAG tags (NTAG213/215/216). Only user memory is
copied - page 4 up to the end of the user area. Everything else stays as it
is on the target, deliberately:

  - pages 0-2 hold the UID, which is burned in at the factory, so the copy
    will always have a different UID from the original;
  - the lock bytes and configuration pages would permanently lock the target
    or password-protect it if copied across.

Both tags are backed up to backup_<UID>.txt before anything is written, so
the target can be put back with:  python nfc_backup.py --restore FILE
"""

import argparse
import os
import sys
import time
import traceback

from smartcard.System import readers
from smartcard.Exceptions import CardConnectionException, NoCardException

from nfc_backup import (Card, Tee, banner, hexs, probe_page_count,
                        read_all_pages, save_dump)

HERE = os.path.dirname(os.path.abspath(__file__))
LOG_PATH = os.path.join(HERE, "last_copy.txt")

FIRST_DATA_PAGE = 4
CC_PAGE = 3

# Page count -> (model, first page AFTER user memory, standard CC size byte).
MODELS_BY_PAGES = {
    20:  ("Ultralight EV1 (MF0UL11)", 16, 0x06),
    41:  ("Ultralight EV1 (MF0UL21)", 36, 0x12),
    45:  ("NTAG213", 40, 0x12),
    135: ("NTAG215", 130, 0x3E),
    231: ("NTAG216", 226, 0x6D),
}


def uid_hex(uid):
    return "".join("%02X" % b for b in uid)


def pick_reader(hint="PICC"):
    found = readers()
    if not found:
        sys.exit("No PC/SC readers found. Is the reader plugged in?")
    for r in found:
        if hint.lower() in str(r).lower():
            return r
    return found[0]


def wait_for_tag(reader, prompt, not_uid=None):
    """Wait for a tag. If not_uid is given, keep waiting while that tag is
    still on the reader, so the source is never mistaken for the target."""
    print(prompt)
    last = None
    while True:
        message = None
        try:
            card = Card(reader)
            uid = card.uid()
            if uid and (not_uid is None or list(uid) != list(not_uid)):
                return card, list(uid)
            card.close()
            message = ("Still seeing the source card - remove it."
                       if uid else "Could not read UID.")
        except (NoCardException, CardConnectionException) as exc:
            message = str(exc).strip()
        if message != last:
            print("  [waiting] %s" % message)
            last = message
        time.sleep(0.25)


def read_tag(card, label):
    """Identify the tag and read every page twice, insisting both reads agree.
    A tag sliding off the reader mid-read can return garbage that looks real."""
    total = probe_page_count(card)
    model = MODELS_BY_PAGES.get(total)
    if not model:
        banner("UNSUPPORTED %s TAG" % label,
               "%d readable pages - not a recognised NTAG/Ultralight." % total)
        return None, None

    for _ in range(3):
        first = read_all_pages(card, total)
        second = read_all_pages(card, total)
        if first == second:
            return first, model
        print("  (reads disagreed - hold the tag still, retrying)")
    banner("CANNOT READ %s TAG RELIABLY" % label, "Keep it flat on the reader.")
    return None, None


def describe(label, uid, pages, model):
    name, user_end, _ = model
    cc = pages[CC_PAGE]
    print("%-7s: %s  UID %s" % (label, name, hexs(uid)))
    print("         capability %s, user pages %d-%d"
          % (hexs(cc) if cc else "UNREADABLE", FIRST_DATA_PAGE, user_end - 1))


def confirm(question):
    if sys.stdin is None or not sys.stdin.isatty():
        print("%s  (no console to answer - rerun with --yes)" % question)
        return False
    try:
        return input("%s [y/N] " % question).strip().lower() == "y"
    except (EOFError, KeyboardInterrupt):
        return False


def main():
    ap = argparse.ArgumentParser(description="Copy one NFC tag onto another.")
    ap.add_argument("--yes", action="store_true",
                    help="do not ask before overwriting the target tag")
    ap.add_argument("--reader", default="PICC",
                    help="pick a reader by name substring (default: PICC)")
    args = ap.parse_args()

    reader = pick_reader(args.reader)
    print("Using reader : %s\n" % reader)

    # ---- 1. source -----------------------------------------------------
    card, src_uid = wait_for_tag(reader, "Tap the SOURCE card (the one to copy FROM)...")
    try:
        src_pages, src_model = read_tag(card, "SOURCE")
    finally:
        card.close()
    if not src_pages:
        return

    _, src_end, _ = src_model
    user = src_pages[FIRST_DATA_PAGE:src_end]
    if any(page is None for page in user) or src_pages[CC_PAGE] is None:
        banner("SOURCE PARTLY UNREADABLE",
               "Probably password protected - cannot copy what cannot be read.")
        return

    print()
    describe("Source", src_uid, src_pages, src_model)
    src_backup = os.path.join(HERE, "backup_%s.txt" % uid_hex(src_uid))
    save_dump(src_backup, src_uid, src_pages)
    print("         saved to %s" % os.path.basename(src_backup))

    # Only the pages up to the last non-blank one actually need to fit.
    used = len(user)
    while used and not any(user[used - 1]):
        used -= 1
    print("         %d of %d user pages hold data\n" % (used, len(user)))

    # ---- 2. target -----------------------------------------------------
    card, tgt_uid = wait_for_tag(
        reader, "Now remove it and tap the TARGET card (the one to copy TO)...",
        not_uid=src_uid)
    try:
        tgt_pages, tgt_model = read_tag(card, "TARGET")
        if not tgt_pages:
            return

        tgt_name, tgt_end, tgt_std_cc = tgt_model
        print()
        describe("Target", tgt_uid, tgt_pages, tgt_model)

        if any(p is None for p in tgt_pages[CC_PAGE:tgt_end]):
            banner("TARGET PARTLY UNREADABLE",
                   "It is probably password protected. Nothing written.")
            return

        tgt_room = tgt_end - FIRST_DATA_PAGE
        if used > tgt_room:
            banner("TARGET TOO SMALL",
                   "Source needs %d pages, %s has %d." % (used, tgt_name, tgt_room))
            return

        # ---- 3. capability container (page 3, one-time programmable) ---
        src_cc, tgt_cc = src_pages[CC_PAGE], tgt_pages[CC_PAGE]
        new_cc = None
        if tgt_cc[0] == 0xE1 and tgt_cc[3] != 0x00:
            banner("TARGET IS READ-ONLY", "Its capability container marks it locked.")
            return
        if src_cc[0] == 0xE1:
            if tgt_cc[0] != 0xE1:
                if any(tgt_cc):
                    banner("TARGET HAS AN ODD CAPABILITY CONTAINER",
                           "%s - page 3 cannot be un-set, refusing." % hexs(tgt_cc))
                    return
                # Use the TARGET's own size byte, never the source's: page 3
                # cannot be corrected afterwards.
                new_cc = [0xE1, 0x10, tgt_std_cc, 0x00]
            capacity = (new_cc or tgt_cc)[2] * 8
            if used * 4 > capacity:
                banner("TARGET TOO SMALL",
                       "NDEF data needs %d bytes, target advertises %d."
                       % (used * 4, capacity))
                return

        # Copy the source's data, then blank the rest so nothing old survives.
        wanted = [list(p) for p in user[:used]]
        wanted += [[0, 0, 0, 0]] * (tgt_room - used)
        changes = [(FIRST_DATA_PAGE + i, page) for i, page in enumerate(wanted)
                   if list(tgt_pages[FIRST_DATA_PAGE + i]) != page]

        if not changes and not new_cc:
            banner("TARGET ALREADY MATCHES", "Nothing to write.")
            return

        tgt_backup = os.path.join(HERE, "backup_%s.txt" % uid_hex(tgt_uid))
        save_dump(tgt_backup, tgt_uid, tgt_pages)
        print("         saved to %s" % os.path.basename(tgt_backup))

        print("\nAbout to write %d page(s) to the target%s."
              % (len(changes), " and format it as NDEF" if new_cc else ""))
        if not args.yes and not confirm("Overwrite the TARGET card?"):
            print("\nCancelled - nothing written.")
            return

        # The tag may have moved while the question was on screen.
        card.reconnect()
        if list(card.uid() or []) != tgt_uid:
            banner("TARGET CARD CHANGED", "A different tag is on the reader now.")
            return

        # ---- 4. write --------------------------------------------------
        print("\nWriting...")
        if new_cc:
            if not card.write_page(CC_PAGE, new_cc):
                banner("FORMAT FAILED", "Could not write the capability container.")
                return
            print("  page %3d <- %s" % (CC_PAGE, hexs(new_cc)))
        failed = []
        for page, data in changes:
            if card.write_page(page, data):
                print("  page %3d <- %s" % (page, hexs(data)))
            else:
                print("  page %3d -- WRITE FAILED" % page)
                failed.append(page)
            # Back-to-back writes make the reader reset the card.
            time.sleep(0.05)

        # ---- 5. verify -------------------------------------------------
        print("\nVerifying by reading the target back...")
        try:
            card.reconnect()
        except Exception:
            pass
        after = read_all_pages(card, tgt_end)
        wrong = [FIRST_DATA_PAGE + i for i, page in enumerate(wanted)
                 if after[FIRST_DATA_PAGE + i] is None
                 or list(after[FIRST_DATA_PAGE + i]) != page]

        if failed or wrong:
            banner("COPY INCOMPLETE",
                   "Pages %s do not match the source."
                   % ", ".join(str(p) for p in sorted(set(failed + wrong))))
            print("\n  Undo with:  python nfc_backup.py --restore \"%s\""
                  % os.path.basename(tgt_backup))
        else:
            banner("COPY COMPLETE",
                   "%d page(s) copied from %s to %s."
                   % (used, uid_hex(src_uid), uid_hex(tgt_uid)))
            print("\n  Note: the UID is not copied - the target keeps its own.")
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
