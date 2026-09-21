#!/usr/bin/env python3
"""
Show what a contactless bank card (Visa, Mastercard, Amex, eftpos...) tells
any reader that asks.

    python nfc_emv.py            # card number masked everywhere
    python nfc_emv.py --unmask   # full number on screen, still masked in the log

Payment cards are EMV smart cards, not storage tags, so there are no pages to
dump. Instead the reader asks the card questions in the same order a shop
terminal does:

  1. SELECT the payment directory (PPSE) to list the card's applications
  2. SELECT each application to get its label and what it wants from a terminal
  3. GET PROCESSING OPTIONS, which returns the list of records to read
  4. READ RECORD for each one - this is where the card number and expiry live
  5. GET DATA for counters, and the transaction log if the card keeps one

What is NOT on the chip, or never leaves it: the CVV on the back, the PIN,
and the card's secret keys. Every tap produces a fresh one-time cryptogram
signed with those keys, which is why this data cannot be used to clone a card.

Nothing is charged: a terminal only takes money by sending the cryptogram to
the bank, and this script never does. The card's transaction counter does go
up by one, the same as any tap.
"""

import argparse
import os
import sys
import time
import traceback

from smartcard.System import readers
from smartcard.Exceptions import CardConnectionException, NoCardException

from nfc_backup import Tee, banner, hexs

LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "last_emv.txt")

PPSE = list(b"2PAY.SYS.DDF01")

# Tried one by one if the card has no payment directory.
KNOWN_AIDS = {
    "A0000000031010": "Visa credit/debit",
    "A0000000032010": "Visa Electron",
    "A0000000032020": "V Pay",
    "A0000000041010": "Mastercard",
    "A0000000043060": "Maestro",
    "A00000002501": "American Express",
    "A0000001523010": "Discover",
    "A0000000651010": "JCB",
    "A000000333010101": "UnionPay debit",
    "A000000333010102": "UnionPay credit",
    "A0000002771010": "Interac",
    "A00000038410": "eftpos (Australia)",
}

TAG_NAMES = {
    0x4F: "Application ID (AID)",
    0x50: "Application label",
    0x56: "Track 1 data",
    0x57: "Track 2 equivalent data",
    0x5A: "Card number (PAN)",
    0x5F20: "Cardholder name",
    0x5F24: "Expiry date",
    0x5F25: "Effective date",
    0x5F28: "Issuer country",
    0x5F2A: "Transaction currency",
    0x5F2D: "Language preference",
    0x5F30: "Service code",
    0x5F34: "PAN sequence number",
    0x61: "Application template",
    0x6F: "File control information",
    0x70: "Record template",
    0x77: "Response template",
    0x80: "Response (AIP + AFL)",
    0x82: "Application interchange profile",
    0x84: "Dedicated file name",
    0x87: "Application priority",
    0x88: "Short file identifier",
    0x8C: "CDOL1 (data for 1st cryptogram)",
    0x8D: "CDOL2 (data for 2nd cryptogram)",
    0x8E: "Cardholder verification method list",
    0x8F: "Certificate authority key index",
    0x90: "Issuer public key certificate",
    0x92: "Issuer public key remainder",
    0x93: "Signed static application data",
    0x94: "Application file locator",
    0x9A: "Transaction date",
    0x9C: "Transaction type",
    0xA5: "FCI proprietary template",
    0xBF0C: "FCI issuer discretionary data",
    0x9F02: "Amount",
    0x9F03: "Amount, other",
    0x9F07: "Application usage control",
    0x9F08: "Application version",
    0x9F0D: "Issuer action code - default",
    0x9F0E: "Issuer action code - denial",
    0x9F0F: "Issuer action code - online",
    0x9F10: "Issuer application data",
    0x9F11: "Issuer code table index",
    0x9F12: "Application preferred name",
    0x9F13: "Last online transaction counter",
    0x9F17: "PIN tries remaining",
    0x9F1A: "Terminal country",
    0x9F1F: "Track 1 discretionary data",
    0x9F20: "Track 2 discretionary data",
    0x9F21: "Transaction time",
    0x9F26: "Application cryptogram",
    0x9F27: "Cryptogram information data",
    0x9F32: "Issuer public key exponent",
    0x9F36: "Application transaction counter",
    0x9F38: "PDOL (data the card wants from the terminal)",
    0x9F42: "Application currency",
    0x9F44: "Currency exponent",
    0x9F46: "Card public key certificate",
    0x9F47: "Card public key exponent",
    0x9F48: "Card public key remainder",
    0x9F49: "DDOL",
    0x9F4A: "Static data authentication tag list",
    0x9F4B: "Signed dynamic application data",
    0x9F4D: "Log entry (where the transaction log is)",
    0x9F4E: "Merchant name",
    0x9F4F: "Log format",
    0x9F5D: "Available offline spending amount",
    0x9F66: "Terminal transaction qualifiers",
    0x9F69: "Card authentication related data",
    0x9F6B: "Track 2 data",
    0x9F6C: "Card transaction qualifiers",
    0x9F6E: "Form factor indicator",
    0x9F7C: "Customer exclusive data",
}

# Tags that carry the card number; never printed raw.
SECRET_TAGS = {0x56, 0x57, 0x5A, 0x9F1F, 0x9F20, 0x9F6B}
# RSA certificate material: long and meaningless to read.
CERT_TAGS = {0x90, 0x92, 0x93, 0x9F46, 0x9F48, 0x9F4B}

COUNTRIES = {
    36: "Australia", 124: "Canada", 156: "China", 250: "France",
    276: "Germany", 344: "Hong Kong", 356: "India", 372: "Ireland",
    392: "Japan", 554: "New Zealand", 702: "Singapore", 710: "South Africa",
    724: "Spain", 826: "United Kingdom", 840: "United States",
}
CURRENCIES = {
    36: "AUD", 124: "CAD", 156: "CNY", 344: "HKD", 356: "INR", 392: "JPY",
    554: "NZD", 702: "SGD", 710: "ZAR", 826: "GBP", 840: "USD", 978: "EUR",
}


# ------------------------------------------------------------ TLV / BER -----
def read_tag(data, i):
    tag = data[i]
    i += 1
    if tag & 0x1F == 0x1F:
        while i < len(data):
            tag = (tag << 8) | data[i]
            i += 1
            if not data[i - 1] & 0x80:
                break
    return tag, i


def parse_tlv(data):
    """Parse BER-TLV into [(tag, value, children-or-None)]."""
    items, i = [], 0
    while i < len(data):
        if data[i] in (0x00, 0xFF):  # padding between objects
            i += 1
            continue
        tag, i = read_tag(data, i)
        if i >= len(data):
            break
        length = data[i]
        i += 1
        if length & 0x80:
            count = length & 0x7F
            length = int.from_bytes(bytes(data[i:i + count]), "big")
            i += count
        value = list(data[i:i + length])
        i += length
        first = tag
        while first > 0xFF:
            first >>= 8
        children = parse_tlv(value) if first & 0x20 else None
        items.append((tag, value, children))
    return items


def flatten(items):
    for tag, value, children in items:
        yield tag, value
        if children:
            yield from flatten(children)


def parse_dol(data):
    """A data object list is tags and lengths with no values."""
    out, i = [], 0
    while i < len(data):
        tag, i = read_tag(data, i)
        if i >= len(data):
            break
        out.append((tag, data[i]))
        i += 1
    return out


# ------------------------------------------------------------ formatting ----
def digits(value):
    return "".join("%02X" % b for b in value)


def bcd_number(value):
    try:
        return int(digits(value))
    except ValueError:
        return None


def yymmdd(value, day=True):
    d = digits(value)
    return ("20%s-%s-%s" % (d[0:2], d[2:4], d[4:6])) if day else ("%s/%s" % (d[2:4], d[0:2]))


def mask_pan(pan):
    shown = pan[:6] + "*" * (len(pan) - 10) + pan[-4:] if len(pan) > 10 else "*" * len(pan)
    return " ".join(shown[i:i + 4] for i in range(0, len(shown), 4))


def group_pan(pan):
    return " ".join(pan[i:i + 4] for i in range(0, len(pan), 4))


def luhn_ok(pan):
    total = 0
    for index, ch in enumerate(reversed(pan)):
        n = int(ch)
        if index % 2:
            n = n * 2 - 9 if n > 4 else n * 2
        total += n
    return total % 10 == 0


def parse_track2(value):
    """Track 2: PAN 'D' YYMM service-code discretionary 'F'-padding."""
    text = digits(value).rstrip("F")
    pan, _, rest = text.partition("D")
    return pan, rest[0:4], rest[4:7]


def as_text(value):
    if value and all(32 <= b < 127 for b in value):
        return bytes(value).decode("ascii")
    return None


def describe(tag, value):
    """One-line human reading of a primitive value. Never returns a PAN."""
    if tag in SECRET_TAGS:
        if tag == 0x5A:
            return mask_pan(digits(value).rstrip("F"))
        if tag in (0x57, 0x9F6B):
            pan, exp, svc = parse_track2(value)
            return "%s, expires %s/%s, service code %s (rest hidden)" % (
                mask_pan(pan), exp[2:4], exp[0:2], svc)
        return "(hidden - contains card details)"
    if tag in CERT_TAGS:
        return "(%d bytes of RSA certificate data)" % len(value)
    if tag in (0x5F24, 0x5F25):
        return "%s  (%s)" % (yymmdd(value, day=False), yymmdd(value))
    if tag == 0x9A:
        return yymmdd(value)
    if tag in (0x5F28, 0x9F1A):
        code = bcd_number(value)
        return "%s (%s)" % (COUNTRIES.get(code, "code"), digits(value))
    if tag in (0x5F2A, 0x9F42, 0x9F51):
        code = bcd_number(value)
        return "%s (%s)" % (CURRENCIES.get(code, "code"), digits(value))
    if tag in (0x9F02, 0x9F03, 0x9F5D):
        cents = bcd_number(value)
        return "%.2f" % (cents / 100) if cents is not None else hexs(value)
    if tag in (0x9F36, 0x9F13, 0x9F17):
        return "%d" % int.from_bytes(bytes(value), "big")
    text = as_text(value)
    if text is not None and len(value) >= 2:
        return '"%s"' % text
    if len(value) > 24:
        return "%s ... (%d bytes)" % (hexs(value[:16]), len(value))
    return hexs(value)


def show_tlvs(items, indent=4):
    for tag, value, children in items:
        name = TAG_NAMES.get(tag, "")
        if children is not None:
            print("%s%-6X %s" % (" " * indent, tag, name))
            show_tlvs(children, indent + 2)
        else:
            print("%s%-6X %-38s %s" % (" " * indent, tag, name, describe(tag, value)))


def show_secret(label, masked, full, unmask):
    """Print full to the screen only; the log file always gets the masked form."""
    out = sys.stdout
    if unmask and isinstance(out, Tee):
        out.stream.write("%s%s\n" % (label, full))
        out.stream.flush()
        out.log.write("%s%s   (full number was shown on screen only)\n" % (label, masked))
        out.log.flush()
    else:
        print("%s%s" % (label, masked))


SERVICE_CODE = [
    {"1": "international", "2": "international, chip", "5": "national",
     "6": "national, chip", "7": "private", "9": "test card"},
    {"0": "normal authorisation", "2": "issuer authorises", "4": "issuer authorises"},
    {"0": "PIN required", "1": "no restrictions", "2": "goods & services only",
     "3": "ATM only, PIN required", "4": "cash only",
     "5": "goods & services, PIN required", "6": "no restrictions, PIN if possible",
     "7": "goods & services, PIN if possible"},
]


def service_code_text(code):
    if len(code) != 3:
        return code
    return "%s (%s)" % (code, "; ".join(
        table.get(ch, "?") for table, ch in zip(SERVICE_CODE, code)))


# -------------------------------------------------------------- card I/O ----
class EmvCard:
    def __init__(self, reader):
        self.conn = reader.createConnection()
        self.conn.connect()

    def atr(self):
        return self.conn.getATR()

    def send(self, apdu):
        data, sw1, sw2 = self.conn.transmit(list(apdu))
        if sw1 == 0x6C:  # wrong Le - resend with the length the card asked for
            data, sw1, sw2 = self.conn.transmit(list(apdu[:-1]) + [sw2])
        while sw1 == 0x61:  # more data waiting
            more, sw1, sw2 = self.conn.transmit([0x00, 0xC0, 0x00, 0x00, sw2])
            data += more
        return data, (sw1 << 8) | sw2

    def select(self, name):
        return self.send([0x00, 0xA4, 0x04, 0x00, len(name)] + list(name) + [0x00])

    def read_record(self, sfi, record):
        return self.send([0x00, 0xB2, record, (sfi << 3) | 4, 0x00])

    def get_data(self, tag):
        data, sw = self.send([0x80, 0xCA, tag >> 8, tag & 0xFF, 0x00])
        if sw != 0x9000:
            return None
        for t, v in flatten(parse_tlv(data)):
            if t == tag:
                return v
        return data or None

    def close(self):
        try:
            self.conn.disconnect()
        except Exception:
            pass


def bcd(n):
    return ((n // 10) << 4) | (n % 10)


def terminal_value(tag, length):
    """What a generic shop terminal would answer for a PDOL entry.
    Zero amount, so nothing is being paid for."""
    now = time.localtime()
    values = {
        0x9F66: [0xB6, 0x20, 0xC0, 0x00],        # TTQ: contactless EMV + online
        0x9F1A: [0x08, 0x40],                    # terminal country
        0x5F2A: [0x08, 0x40],                    # transaction currency
        0x9A: [bcd(now.tm_year % 100), bcd(now.tm_mon), bcd(now.tm_mday)],
        0x9F21: [bcd(now.tm_hour), bcd(now.tm_min), bcd(now.tm_sec)],
        0x9C: [0x00],                            # purchase
        0x9F35: [0x22],                          # attended, offline-capable
        0x9F33: [0xE0, 0xF8, 0xC8],              # terminal capabilities
        0x9F37: list(os.urandom(4)),             # unpredictable number
        0x9F4C: list(os.urandom(8)),
    }
    value = values.get(tag, [])
    return (value + [0] * length)[:length]


# ---------------------------------------------------------------- reading ---
def list_applications(card):
    data, sw = card.select(PPSE)
    apps = []
    if sw == 0x9000:
        tree = parse_tlv(data)
        print("\n-- Payment directory (PPSE) --")
        show_tlvs(tree)
        for tag, value, children in _walk(tree):
            if tag == 0x61 and children:
                fields = dict(flatten(children))
                if 0x4F in fields:
                    label = as_text(fields.get(0x50, [])) or ""
                    apps.append((fields[0x4F], label))
    if not apps:
        print("\nNo payment directory - trying the well-known application IDs...")
        for aid_hex, brand in KNOWN_AIDS.items():
            aid = list(bytes.fromhex(aid_hex))
            _, sw = card.select(aid)
            if sw == 0x9000:
                apps.append((aid, brand))
    return apps


def _walk(items):
    for item in items:
        yield item
        if item[2]:
            yield from _walk(item[2])


def read_application(card, aid, label, unmask):
    title = "%s  (%s)" % (label or KNOWN_AIDS.get(digits(aid), "Unknown app"), digits(aid))
    print("\n" + "=" * 70)
    print("  Application: %s" % title)
    print("=" * 70)

    found = {}

    def collect(items):
        for tag, value in flatten(items):
            found.setdefault(tag, value)

    data, sw = card.select(aid)
    if sw != 0x9000:
        print("  SELECT failed (SW %04X)" % sw)
        return
    fci = parse_tlv(data)
    collect(fci)
    print("\n-- Selected application --")
    show_tlvs(fci)

    # GET PROCESSING OPTIONS: fill in whatever the card asked for in its PDOL.
    pdol = parse_dol(found.get(0x9F38, []))
    pdol_data = [b for tag, length in pdol for b in terminal_value(tag, length)]
    gpo, sw = card.send([0x80, 0xA8, 0x00, 0x00, len(pdol_data) + 2, 0x83,
                         len(pdol_data)] + pdol_data + [0x00])
    afl = []
    if sw == 0x9000:
        tree = parse_tlv(gpo)
        print("\n-- Processing options --")
        show_tlvs(tree)
        collect(tree)
        if tree and tree[0][0] == 0x80:  # format 1: AIP (2 bytes) then AFL
            afl = tree[0][1][2:]
        else:
            afl = found.get(0x94, [])
    else:
        print("\n  GET PROCESSING OPTIONS refused (SW %04X) - scanning records instead." % sw)

    # READ RECORD everything the AFL points to, or brute-force if there is none.
    if afl:
        locations = [(afl[i] >> 3, rec) for i in range(0, len(afl) - 3, 4)
                     for rec in range(afl[i + 1], afl[i + 2] + 1)]
    else:
        locations = [(sfi, rec) for sfi in range(1, 11) for rec in range(1, 17)]

    print("\n-- Records --")
    dead_sfi = set()
    for sfi, rec in locations:
        if sfi in dead_sfi:
            continue
        data, sw = card.read_record(sfi, rec)
        if sw != 0x9000:
            if not afl:
                dead_sfi.add(sfi)  # this file has no more records
            continue
        tree = parse_tlv(data)
        print("  SFI %d record %d:" % (sfi, rec))
        show_tlvs(tree, indent=4)
        collect(tree)

    # Counters kept on the card, outside the records.
    for tag in (0x9F36, 0x9F13, 0x9F17):
        if tag not in found:
            value = card.get_data(tag)
            if value:
                found[tag] = value

    print_summary(found, title, unmask)
    print_log(card, found)


def print_summary(found, title, unmask):
    print("\n-- Summary: %s --" % title)
    pan = expiry = service = None
    if 0x5A in found:
        pan = digits(found[0x5A]).rstrip("F")
    for tag in (0x57, 0x9F6B):
        if tag in found:
            t_pan, t_exp, t_svc = parse_track2(found[tag])
            pan = pan or t_pan
            expiry = expiry or t_exp
            service = service or t_svc

    if pan:
        check = "checksum OK" if luhn_ok(pan) else "checksum FAILS"
        show_secret("  Card number      : ",
                    "%s   (%d digits, %s)" % (mask_pan(pan), len(pan), check),
                    "%s   (%d digits, %s)" % (group_pan(pan), len(pan), check),
                    unmask)
    else:
        print("  Card number      : (not found)")

    if 0x5F24 in found:
        print("  Expires          : %s" % yymmdd(found[0x5F24], day=False))
    elif expiry:
        print("  Expires          : %s/%s" % (expiry[2:4], expiry[0:2]))
    if 0x5F25 in found:
        print("  Valid from       : %s" % yymmdd(found[0x5F25], day=False))

    name = (as_text(found.get(0x5F20, [])) or "").strip(" /")
    print("  Name on chip     : %s" % (name or "(not stored - most new cards leave it out)"))

    for tag, label in ((0x5F28, "Issued in"), (0x9F42, "Card currency")):
        if tag in found:
            print("  %-17s: %s" % (label, describe(tag, found[tag])))
    service = service or (digits(found[0x5F30])[-3:] if 0x5F30 in found else None)
    if service:
        print("  Service code     : %s" % service_code_text(service))
    if 0x5F34 in found:
        print("  Card issue no.   : %s" % digits(found[0x5F34]))
    if 0x9F36 in found:
        print("  Taps/payments    : %s  (the card's own counter)" % describe(0x9F36, found[0x9F36]))
    if 0x9F17 in found:
        print("  PIN tries left   : %s" % describe(0x9F17, found[0x9F17]))
    if 0x9F5D in found:
        print("  Offline balance  : %s" % describe(0x9F5D, found[0x9F5D]))


def print_log(card, found):
    entry = found.get(0x9F4D)
    if not entry or len(entry) < 2:
        print("\n  Transaction log  : this card does not keep one")
        return
    sfi, count = entry[0], entry[1]
    fmt = parse_dol(card.get_data(0x9F4F) or [])
    if not fmt:
        print("\n  Transaction log  : present, but the card would not give its format")
        return

    print("\n-- Transaction log (last %d kept on the card) --" % count)
    columns = [TAG_NAMES.get(tag, "%X" % tag) for tag, _ in fmt]
    print("    " + " | ".join(columns))
    shown = 0
    for rec in range(1, count + 1):
        data, sw = card.read_record(sfi, rec)
        if sw != 0x9000 or not any(data):
            continue
        cells, i = [], 0
        for tag, length in fmt:
            cells.append(describe(tag, data[i:i + length]))
            i += length
        print("    " + " | ".join(cells))
        shown += 1
    if not shown:
        print("    (empty)")


# ------------------------------------------------------------------ main ----
def pick_reader(hint):
    found = readers()
    if not found:
        sys.exit("No PC/SC readers found. Is the reader plugged in?")
    for r in found:
        if hint.lower() in str(r).lower():
            return r
    return found[0]


def wait_for_card(reader):
    print("Hold the bank card flat on the reader and keep it there...")
    last = None
    while True:
        try:
            return EmvCard(reader)
        except (NoCardException, CardConnectionException) as exc:
            message = str(exc).strip()
            if message != last:
                print("  [waiting] %s" % message)
                last = message
            time.sleep(0.25)


def main():
    ap = argparse.ArgumentParser(description="Read the public data on a contactless bank card.")
    ap.add_argument("--unmask", action="store_true",
                    help="show the full card number on screen (the log stays masked)")
    ap.add_argument("--reader", default="PICC",
                    help="pick a reader by name substring (default: PICC)")
    args = ap.parse_args()

    reader = pick_reader(args.reader)
    print("Using reader : %s\n" % reader)

    card = wait_for_card(reader)
    try:
        print("ATR          : %s" % hexs(card.atr()))
        apps = list_applications(card)
        if not apps:
            banner("NO PAYMENT APPLICATION FOUND",
                   "This does not look like a bank card (or it left the reader).")
            return
        for aid, label in apps:
            read_application(card, aid, label, args.unmask)

        print("\nNot on the chip: CVV/security code, PIN, or the card's secret keys.")
        banner("DONE", "Read %d payment application(s)." % len(apps))
    except CardConnectionException:
        banner("CARD LEFT THE READER", "Keep it still until DONE appears, then retry.")
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
