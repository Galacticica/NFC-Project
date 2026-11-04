#!/usr/bin/env python3
"""
Read and print the contents of an NFC card using an ACS ACR1552U
(or any PC/SC contactless reader).

    python nfc_read.py              # read one card, print everything, exit
    python nfc_read.py --watch      # keep reading cards until Ctrl-C
    python nfc_read.py --keys-only  # UID + card type only, no memory dump

Supports:
  * MIFARE Classic 1K/4K/Mini  - authenticates with common default keys
  * MIFARE Ultralight / NTAG   - full page dump
  * ISO 14443-4 (DESFire, JCOP, phones) - NFC Forum Type 4 NDEF read
and decodes any NDEF message it finds (text and URI records included).
"""

import argparse
import os
import sys
import time
import traceback

from smartcard.System import readers
from smartcard.util import toHexString
from smartcard.Exceptions import CardConnectionException, NoCardException

# ---------------------------------------------------------------- APDUs -----
GET_UID = [0xFF, 0xCA, 0x00, 0x00, 0x00]
GET_ATS = [0xFF, 0xCA, 0x01, 0x00, 0x00]

# MIFARE Classic keys worth trying, in order.
DEFAULT_KEYS = [
    [0xFF] * 6,                               # factory default
    [0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5],     # MAD key A
    [0xD3, 0xF7, 0xD3, 0xF7, 0xD3, 0xF7],     # NDEF public key
    [0x00] * 6,
    [0xB0, 0xB1, 0xB2, 0xB3, 0xB4, 0xB5],
    [0x4D, 0x3A, 0x99, 0xC3, 0x51, 0xDD],
    [0x1A, 0x98, 0x2C, 0x7E, 0x45, 0x9A],
    [0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF],
]

# PC/SC part 3 card-name codes found in a contactless storage-card ATR.
CARD_NAMES = {
    0x0001: "MIFARE Classic 1K",
    0x0002: "MIFARE Classic 4K",
    0x0003: "MIFARE Ultralight",
    0x0026: "MIFARE Mini",
    0x003A: "MIFARE Ultralight C",
    0x0036: "MIFARE Plus SL1 2K",
    0x0037: "MIFARE Plus SL1 4K",
    0x0038: "MIFARE Plus SL2 2K",
    0x0039: "MIFARE Plus SL2 4K",
    0xF004: "Topaz / Jewel",
    0xF011: "FeliCa 212k",
    0xF012: "FeliCa 424k",
    0xFF28: "JCOP 30",
}

# Capability-container size byte -> (tag model, total pages). Ultralight EV1
# and NTAG213 share the 0x12 code, so that entry names both.
NTAG_SIZES = {
    0x06: ("Ultralight EV1 (MF0UL11)", 20),
    0x12: ("NTAG213 / Ultralight EV1 (MF0UL21)", 45),
    0x3E: ("NTAG215", 135),
    0x6D: ("NTAG216", 231),
}

URI_PREFIXES = [
    "", "http://www.", "https://www.", "http://", "https://", "tel:", "mailto:",
    "ftp://anonymous:anonymous@", "ftp://ftp.", "ftps://", "sftp://", "smb://",
    "nfs://", "ftp://", "dav://", "news:", "telnet://", "imap:", "rtsp://",
    "urn:", "pop:", "sip:", "sips:", "tftp:", "btspp://", "btl2cap://",
    "btgoep://", "tcpobex://", "irdaobex://", "file://", "urn:epc:id:",
    "urn:epc:tag:", "urn:epc:pat:", "urn:epc:raw:", "urn:epc:", "urn:nfc:",
]

TNF_NAMES = {
    0x00: "Empty", 0x01: "NFC Forum well-known", 0x02: "MIME media",
    0x03: "Absolute URI", 0x04: "NFC Forum external", 0x05: "Unknown",
    0x06: "Unchanged", 0x07: "Reserved",
}


# ------------------------------------------------------------- helpers ------
def hexs(data):
    return toHexString(list(data))


def printable(data):
    return "".join(chr(b) if 0x20 <= b < 0x7F else "." for b in data)


LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "last_read.txt")


class Tee:
    """Mirror everything printed into a log file, so the results survive even
    if the console window closes instantly (e.g. on a double-click launch)."""

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


def banner(headline, detail=""):
    width = max(len(headline), len(detail)) + 4
    print("\n  +" + "-" * width + "+")
    print("  | %-*s |" % (width - 2, headline))
    if detail:
        print("  | %-*s |" % (width - 2, detail))
    print("  +" + "-" * width + "+")


def hexdump(data, width=16, label="offset"):
    for off in range(0, len(data), width):
        chunk = data[off:off + width]
        print("  %s %3d | %-*s | %s" % (
            label, off // width, width * 3 - 1, hexs(chunk), printable(chunk)))


class Card:
    """Thin wrapper that keeps the last status word and can reconnect."""

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
        """MIFARE Classic halts after a failed auth; a reconnect revives it."""
        try:
            self.conn.disconnect()
        except Exception:
            pass
        time.sleep(0.05)
        self.conn.connect()

    def atr(self):
        return self.conn.getATR()

    def close(self):
        try:
            self.conn.disconnect()
        except Exception:
            pass


# ------------------------------------------------------- identification -----
def identify(atr):
    """Return (name, card code, standard) derived from the ATR."""
    # Contactless storage cards use the PC/SC part-3 synthetic ATR:
    # 3B 8F 80 01 80 4F 0C A0 00 00 03 06 SS CC CC 00 00 00 00 TCK
    if (len(atr) >= 17 and atr[:8] == [0x3B, 0x8F, 0x80, 0x01, 0x80, 0x4F, 0x0C, 0xA0]
            and atr[8:11] == [0x00, 0x00, 0x03]):
        code = (atr[13] << 8) | atr[14]
        standard = {0x03: "ISO 14443-A part 3",
                    0x11: "FeliCa"}.get(atr[12], "std 0x%02X" % atr[12])
        return CARD_NAMES.get(code, "unknown storage card (0x%04X)" % code), code, standard
    return "ISO 14443-4 / smart card (not a storage card)", None, "ISO 14443-4"


# ----------------------------------------------------- MIFARE Classic -------
def classic_sector_layout(kind):
    """Yield (sector, first_block, block_count)."""
    if "4K" in kind:
        for s in range(32):
            yield s, s * 4, 4
        for s in range(32, 40):
            yield s, 128 + (s - 32) * 16, 16
    elif "Mini" in kind:
        for s in range(5):
            yield s, s * 4, 4
    else:  # 1K
        for s in range(16):
            yield s, s * 4, 4


def classic_auth(card, block, key, key_type):
    """key_type: 0x60 = key A, 0x61 = key B. Uses reader key slot 0."""
    card.send([0xFF, 0x82, 0x00, 0x00, 0x06] + key)
    if not card.ok():
        return False
    card.send([0xFF, 0x86, 0x00, 0x00, 0x05, 0x01, 0x00, block, key_type, 0x00])
    return card.ok()


def read_classic(card, kind):
    print("\n-- MIFARE Classic memory --")
    for sector, first, count in classic_sector_layout(kind):
        used_key = None
        for key in DEFAULT_KEYS:
            for key_type, name in ((0x60, "A"), (0x61, "B")):
                try:
                    if classic_auth(card, first, key, key_type):
                        used_key = (hexs(key), name)
                        break
                    card.reconnect()
                except CardConnectionException:
                    card.reconnect()
            if used_key:
                break
        if not used_key:
            print("\n  sector %2d  -- locked (no default key worked)" % sector)
            continue

        print("\n  sector %2d  key %s = %s" % (sector, used_key[1], used_key[0]))
        for i in range(count):
            block = first + i
            data, sw1, sw2 = card.send([0xFF, 0xB0, 0x00, block, 0x10])
            if card.ok():
                tag = "  <- trailer (keys/access bits)" if i == count - 1 else ""
                print("    block %3d | %-47s | %s%s"
                      % (block, hexs(data), printable(data), tag))
            else:
                print("    block %3d | read failed (SW %02X%02X)" % (block, sw1, sw2))


# --------------------------------------------- MIFARE Ultralight / NTAG -----
def read_ultralight(card, max_pages=256):
    # The capability container byte gives the NDEF data-area size, which
    # identifies the exact tag and therefore its real page count. Without it
    # the last read runs past the end and wraps back to page 0, so the dump
    # shows a phantom copy of page 0 at the end.
    header, _, _ = card.send([0xFF, 0xB0, 0x00, 0x00, 0x10])
    if not card.ok() or len(header) < 16:
        print("\n  Could not read page 0 (SW %02X%02X)." % card.sw)
        return None

    model, total_pages = NTAG_SIZES.get(header[14], (None, None))
    print("\n-- %s pages (4 bytes each) --"
          % (model if model else "Ultralight / NTAG"))

    pages = bytearray()
    page = 0
    limit = total_pages if total_pages else max_pages
    first_chunk = None
    while page < limit:
        data, _, _ = card.send([0xFF, 0xB0, 0x00, page, 0x10])
        if not card.ok() or len(data) < 16:
            break
        # Reads past the end of memory wrap around to page 0 on these tags.
        if first_chunk is None:
            first_chunk = bytes(data)
        elif bytes(data) == first_chunk:
            break
        pages.extend(data)
        page += 4
    del pages[limit * 4:]  # drop any wrapped-around tail
    hexdump(pages, width=4, label="page")

    print("\n  UID/serial : %s" % hexs(pages[0:3] + pages[4:8]))
    print("  BCC0/BCC1  : %02X %02X" % (pages[3], pages[8]))
    print("  internal   : %02X   lock bytes: %02X %02X"
          % (pages[9], pages[10], pages[11]))
    cc = pages[12:16]
    print("  capability : %s" % hexs(cc))
    if cc[0] == 0xE1:
        print("               NDEF formatted, version %d.%d, %d bytes usable, %s"
              % (cc[1] >> 4, cc[1] & 0x0F, cc[2] * 8,
                 "read-only" if cc[3] else "read/write"))
    return bytes(pages[16:])  # the data area starts at page 4


# ------------------------------------------------- NFC Forum Type 4 tag -----
def read_type4(card):
    print("\n-- ISO 14443-4 / Type 4 tag --")
    card.send([0x00, 0xA4, 0x04, 0x00, 0x07,
               0xD2, 0x76, 0x00, 0x00, 0x85, 0x01, 0x01, 0x00])
    if not card.ok():
        print("  No NDEF application (SW %02X%02X)." % card.sw)
        print("  The card is an ISO 14443-4 device; reading further needs "
              "application-specific commands.")
        return None
    print("  NDEF application selected.")

    card.send([0x00, 0xA4, 0x00, 0x0C, 0x02, 0xE1, 0x03])
    if not card.ok():
        print("  Capability container not readable (SW %02X%02X)." % card.sw)
        return None
    cc, _, _ = card.send([0x00, 0xB0, 0x00, 0x00, 0x0F])
    if not card.ok() or len(cc) < 15:
        print("  Capability container read failed (SW %02X%02X)." % card.sw)
        return None
    file_id = cc[9:11]
    max_size = (cc[11] << 8) | cc[12]
    print("  CC: %s" % hexs(cc))
    print("  NDEF file %s, max %d bytes, %s"
          % (hexs(file_id), max_size, "read-only" if cc[14] else "read/write"))

    card.send([0x00, 0xA4, 0x00, 0x0C, 0x02] + list(file_id))
    if not card.ok():
        print("  Could not select the NDEF file (SW %02X%02X)." % card.sw)
        return None
    nlen, _, _ = card.send([0x00, 0xB0, 0x00, 0x00, 0x02])
    if not card.ok() or len(nlen) < 2:
        return None
    length = (nlen[0] << 8) | nlen[1]
    print("  NDEF message length: %d bytes" % length)
    if length == 0:
        return b""

    message = bytearray()
    offset = 2
    while len(message) < length:
        want = min(0xF0, length - len(message))
        chunk, _, _ = card.send([0x00, 0xB0, offset >> 8, offset & 0xFF, want])
        if not card.ok() or not chunk:
            break
        message.extend(chunk)
        offset += len(chunk)
    return bytes(message)


# ---------------------------------------------------------- NDEF decode -----
def find_ndef_tlv(data):
    """Pull the NDEF message out of a Type 2 tag's TLV data area."""
    i = 0
    while i < len(data):
        t = data[i]
        if t == 0x00:                      # NULL TLV, skip
            i += 1
            continue
        if t == 0xFE:                      # terminator
            return None
        if i + 1 >= len(data):
            return None
        length = data[i + 1]
        i += 2
        if length == 0xFF:                 # 3-byte length form
            if i + 1 >= len(data):
                return None
            length = (data[i] << 8) | data[i + 1]
            i += 2
        if t == 0x03:
            return data[i:i + length]
        i += length
    return None


def decode_ndef(message):
    if not message:
        return
    print("\n-- NDEF message (%d bytes) --" % len(message))
    i = 0
    index = 0
    while i < len(message):
        header = message[i]
        tnf = header & 0x07
        short = bool(header & 0x10)
        has_id = bool(header & 0x08)
        i += 1
        if i >= len(message):
            break
        type_len = message[i]
        i += 1
        if short:
            payload_len = message[i]
            i += 1
        else:
            payload_len = int.from_bytes(message[i:i + 4], "big")
            i += 4
        id_len = 0
        if has_id:
            id_len = message[i]
            i += 1
        rtype = message[i:i + type_len]
        i += type_len
        rid = message[i:i + id_len]
        i += id_len
        payload = message[i:i + payload_len]
        i += payload_len

        index += 1
        print("\n  record %d" % index)
        print("    TNF     : 0x%02X (%s)" % (tnf, TNF_NAMES.get(tnf, "?")))
        print("    type    : %s%s"
              % (printable(rtype), "  [%s]" % hexs(rtype) if rtype else ""))
        if rid:
            print("    id      : %s" % printable(rid))

        if tnf == 0x01 and rtype == b"T" and payload:
            status = payload[0]
            lang_len = status & 0x3F
            enc = "utf-16" if status & 0x80 else "utf-8"
            lang = payload[1:1 + lang_len].decode("ascii", "replace")
            text = payload[1 + lang_len:].decode(enc, "replace")
            print("    text    : %s   (lang %s, %s)" % (text, lang, enc))
        elif tnf == 0x01 and rtype == b"U" and payload:
            prefix = URI_PREFIXES[payload[0]] if payload[0] < len(URI_PREFIXES) else ""
            print("    uri     : %s%s" % (prefix, payload[1:].decode("utf-8", "replace")))
        elif tnf == 0x02:
            print("    payload : %s" % payload.decode("utf-8", "replace"))
        else:
            print("    payload : %d bytes" % payload_len)
            if payload:
                hexdump(payload, width=16, label="line ")

        if header & 0x40:  # message end
            break


# ---------------------------------------------------------------- main ------
def pick_reader(name_hint):
    found = readers()
    if not found:
        sys.exit("No PC/SC readers found. Is the ACR1552U plugged in and the "
                 "Smart Card service running?")
    for r in found:
        if name_hint.lower() in str(r).lower():
            return r
    print("No reader matched %r. Readers found:" % name_hint)
    for r in found:
        print("  -", r)
    return found[0]


def read_card(reader, keys_only=False):
    card = Card(reader)
    try:
        atr = card.atr()
        kind, code, standard = identify(atr)
        print("=" * 72)
        print("ATR        : %s" % hexs(atr))
        print("Card type  : %s" % kind)
        print("Standard   : %s" % standard)

        uid, sw1, sw2 = card.send(GET_UID)
        if card.ok():
            print("UID        : %s   (%d bytes)" % (hexs(uid), len(uid)))
        else:
            print("UID        : unavailable (SW %02X%02X)" % (sw1, sw2))

        ats, _, _ = card.send(GET_ATS)
        if card.ok() and ats:
            print("ATS/hist   : %s" % hexs(ats))

        if keys_only:
            return

        if code in (0x0001, 0x0002, 0x0026):
            read_classic(card, kind)
        else:
            if code is not None:
                data = read_ultralight(card)
                message = find_ndef_tlv(data) if data is not None else None
            else:
                message = read_type4(card)

            # Distinguish "no NDEF structure at all" from "formatted but
            # nothing stored" -- silence for either one reads as a failure.
            # A verdict line, banner-framed so it stands out from the long
            # page dump above it rather than scrolling past unnoticed.
            if message is None:
                banner("CARD IS EMPTY",
                       "No NDEF structure found - nothing has been stored here.")
            elif not message:
                banner("CARD IS EMPTY",
                       "NDEF formatted and ready to write, but no records yet.")
            else:
                banner("CARD HAS DATA", "%d bytes of NDEF content." % len(message))
                decode_ndef(message)
        print("=" * 72)
    finally:
        card.close()


def card_present(reader):
    try:
        c = Card(reader)
        c.close()
        return True
    except (NoCardException, CardConnectionException):
        return False


def main():
    ap = argparse.ArgumentParser(description="Read and print NFC card data.")
    ap.add_argument("--reader", default="PICC",
                    help="substring of the reader name to use (default: PICC)")
    ap.add_argument("--watch", action="store_true",
                    help="keep reading cards as they are presented")
    ap.add_argument("--keys-only", action="store_true",
                    help="print UID and card type only, skip the memory dump")
    args = ap.parse_args()

    reader = pick_reader(args.reader)
    print("Using reader: %s\n" % reader)

    try:
        while True:
            print("Present a card to the reader...")
            last_error = None
            while True:
                try:
                    read_card(reader, args.keys_only)
                    break
                except (NoCardException, CardConnectionException) as exc:
                    # Say why we are still waiting, but only when it changes,
                    # so a genuine problem is not mistaken for an absent card.
                    message = str(exc).strip()
                    if message != last_error:
                        print("  [waiting] %s" % message)
                        last_error = message
                    time.sleep(0.25)
            if not args.watch:
                return
            print("\nRemove the card.\n")
            while card_present(reader):
                time.sleep(0.3)
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    sys.stdout = Tee(sys.stdout, LOG_PATH)
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        # Print the failure rather than letting the window vanish with it.
        print("\n*** The program hit an error ***\n")
        traceback.print_exc(file=sys.stdout)
    finally:
        print("\nThis output was also saved to:\n  %s" % LOG_PATH)
        # Hold the window open when launched by double-click, where there is
        # no shell to return to and the console would close immediately.
        if sys.stdin is not None and sys.stdin.isatty():
            try:
                input("\nPress Enter to close...")
            except (EOFError, KeyboardInterrupt):
                pass
