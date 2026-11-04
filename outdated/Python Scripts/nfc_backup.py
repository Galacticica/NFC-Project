#!/usr/bin/env python3
"""
Back up and restore the full contents of an NFC tag.

    python nfc_backup.py                     # dump the tag to backup_<UID>.txt
    python nfc_backup.py --restore FILE      # write a dump back to the tag
    python nfc_backup.py --compare FILE      # show what differs, change nothing

Take a backup BEFORE writing to any card you care about. Pages 0-2 (UID) are
permanently read-only and page 3 (the capability container) is one-time
programmable, so a restore can only rewrite page 4 onward - that is where
user data lives.
"""

import argparse
import os
import sys
import time
import traceback

from smartcard.System import readers
from smartcard.util import toHexString
from smartcard.Exceptions import CardConnectionException, NoCardException

FIRST_WRITABLE_PAGE = 4
LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "last_backup.txt")


class Tee:
    def __init__(self, stream, path):
        self.stream = stream
        self.log = open(path, "w", encoding="utf-8")

    def write(self, text):
        self.stream.write(text)
        self.stream.flush()
        self.log.write(text)
        self.log.flush()
        return len(text)

    def flush(self):
        self.stream.flush()
        self.log.flush()


def hexs(data):
    return toHexString(list(data))


def banner(headline, detail=""):
    width = max(len(headline), len(detail)) + 4
    print("\n  +" + "-" * width + "+")
    print("  | %-*s |" % (width - 2, headline))
    if detail:
        print("  | %-*s |" % (width - 2, detail))
    print("  +" + "-" * width + "+")


class Card:
    def __init__(self, reader):
        self.reader = reader
        self.conn = reader.createConnection()
        self.conn.connect()
        self.sw = (0, 0)

    def send(self, apdu):
        data, sw1, sw2 = self.conn.transmit(list(apdu))
        self.sw = (sw1, sw2)
        return data, sw1, sw2

    def ok(self):
        return self.sw == (0x90, 0x00)

    def reconnect(self):
        try:
            self.conn.disconnect()
        except Exception:
            pass
        time.sleep(0.05)
        self.conn = self.reader.createConnection()
        self.conn.connect()

    def uid(self):
        data, _, _ = self.send([0xFF, 0xCA, 0x00, 0x00, 0x00])
        return data if self.ok() else None

    def read_single(self, page):
        try:
            data, _, _ = self.send([0xFF, 0xB0, 0x00, page, 0x04])
            return data[:4] if self.ok() and len(data) >= 4 else None
        except CardConnectionException:
            return None

    def write_page(self, page, four_bytes, attempts=3):
        for attempt in range(attempts):
            try:
                self.send([0xFF, 0xD6, 0x00, page, 0x04] + list(four_bytes))
                if self.ok():
                    return True
            except CardConnectionException:
                pass
            if attempt < attempts - 1:
                try:
                    self.reconnect()
                except Exception:
                    time.sleep(0.3)
        return False

    def close(self):
        try:
            self.conn.disconnect()
        except Exception:
            pass


def probe_page_count(card):
    """Highest readable page + 1, found by binary search."""
    lo, hi, best = 0, 255, 0
    while lo <= hi:
        mid = (lo + hi) // 2
        if card.read_single(mid) is not None:
            best = mid
            lo = mid + 1
        else:
            try:
                card.reconnect()
            except Exception:
                pass
            hi = mid - 1
    return best + 1


def read_all_pages(card, total):
    """Read page by page. Slower than bulk reads, but never confuses a
    roll-over at the end of memory for real data."""
    pages = []
    for page in range(total):
        data = card.read_single(page)
        if data is None:
            try:
                card.reconnect()
            except Exception:
                pass
            data = card.read_single(page)
        pages.append(list(data) if data else None)
    return pages


def wait_for_card(reader):
    print("Present the card...")
    last = None
    while True:
        try:
            return Card(reader)
        except (NoCardException, CardConnectionException) as exc:
            message = str(exc).strip()
            if message != last:
                print("  [waiting] %s" % message)
                last = message
            time.sleep(0.25)


def save_dump(path, uid, pages):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("# NFC tag dump\n")
        handle.write("# UID: %s\n" % hexs(uid))
        handle.write("# pages: %d\n" % len(pages))
        for index, page in enumerate(pages):
            handle.write("%3d: %s\n"
                         % (index, hexs(page) if page else "UNREADABLE"))


def load_dump(path):
    uid, pages = None, {}
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line.startswith("# UID:"):
                uid = [int(b, 16) for b in line.split(":", 1)[1].split()]
            elif line and not line.startswith("#"):
                number, _, rest = line.partition(":")
                rest = rest.strip()
                if rest and rest != "UNREADABLE":
                    pages[int(number)] = [int(b, 16) for b in rest.split()]
    return uid, pages


def main():
    ap = argparse.ArgumentParser(description="Back up or restore an NFC tag.")
    ap.add_argument("--restore", metavar="FILE", help="write a saved dump back")
    ap.add_argument("--compare", metavar="FILE", help="compare tag against a dump")
    ap.add_argument("--out", metavar="FILE", help="backup filename to write")
    args = ap.parse_args()

    found = readers()
    if not found:
        sys.exit("No PC/SC readers found.")
    reader = next((r for r in found if "PICC" in str(r)), found[0])
    print("Using reader : %s\n" % reader)

    card = wait_for_card(reader)
    try:
        uid = card.uid() or []
        total = probe_page_count(card)
        print("UID          : %s" % hexs(uid))
        print("Pages        : %d\n" % total)

        if args.restore or args.compare:
            path = args.restore or args.compare
            saved_uid, saved_pages = load_dump(path)
            print("Dump file    : %s" % path)
            print("Dump UID     : %s" % hexs(saved_uid or []))

            if saved_uid and list(saved_uid) != list(uid):
                banner("WRONG CARD",
                       "This dump belongs to a different tag. Refusing.")
                return

            current = read_all_pages(card, total)
            differences = []
            for page, want in sorted(saved_pages.items()):
                if page >= total:
                    continue
                have = current[page]
                if have is not None and list(have) != list(want):
                    differences.append((page, have, want))

            if not differences:
                banner("TAG MATCHES THE BACKUP", "Nothing needs restoring.")
                return

            print("\nDifferences (page: on tag -> in backup):")
            for page, have, want in differences:
                print("  page %3d: %s -> %s" % (page, hexs(have), hexs(want)))

            if args.compare:
                print("\n(--compare: nothing was written)")
                return

            restorable = [d for d in differences if d[0] >= FIRST_WRITABLE_PAGE]
            skipped = [d for d in differences if d[0] < FIRST_WRITABLE_PAGE]
            if skipped:
                print("\nSkipping pages %s - UID and capability bytes are not"
                      % ", ".join(str(d[0]) for d in skipped))
                print("rewritable (read-only / one-time programmable).")

            print("\nRestoring %d page(s)..." % len(restorable))
            failed = []
            for page, _, want in restorable:
                if card.write_page(page, want):
                    print("  page %3d <- %s" % (page, hexs(want)))
                else:
                    print("  page %3d -- WRITE FAILED" % page)
                    failed.append(page)
                time.sleep(0.05)

            if failed:
                banner("RESTORE INCOMPLETE",
                       "Pages %s could not be written."
                       % ", ".join(str(p) for p in failed))
            else:
                banner("RESTORE COMPLETE",
                       "%d page(s) written back." % len(restorable))
            return

        # Default action: take a backup.
        pages = read_all_pages(card, total)
        for index, page in enumerate(pages):
            print("  page %3d | %s" % (index, hexs(page) if page else "UNREADABLE"))

        name = args.out or ("backup_%s.txt" % "".join("%02X" % b for b in uid))
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), name)
        save_dump(path, uid, pages)
        banner("BACKUP SAVED", os.path.basename(path))
        print("\n  Restore later with:")
        print("    python nfc_backup.py --restore \"%s\"" % os.path.basename(path))
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
