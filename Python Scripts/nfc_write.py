#!/usr/bin/env python3
"""
Write a URL to an NFC tag as an NDEF URI record, so that tapping the tag with
an Android phone or iPhone offers to open the site.

    python nfc_write.py                       # writes the default URL below
    python nfc_write.py https://example.com   # writes any other URL
    python nfc_write.py --verify-only         # read back without writing

Targets MIFARE Ultralight / NTAG tags (NTAG213/215/216), which is what a
contactless reader such as the ACR1552U sees as "MIFARE Ultralight".
"""

import argparse
import os
import sys
import time
import traceback

from smartcard.System import readers
from smartcard.util import toHexString
from smartcard.Exceptions import CardConnectionException, NoCardException

DEFAULT_URL = "https://www.reaganzierke.com/development-portfolio/wheel/"

# NDEF URI prefixes; the index is stored as the first payload byte so common
# scheme text does not eat into the tag's limited memory.
URI_PREFIXES = [
    "", "http://www.", "https://www.", "http://", "https://", "tel:", "mailto:",
    "ftp://anonymous:anonymous@", "ftp://ftp.", "ftps://", "sftp://", "smb://",
    "nfs://", "ftp://", "dav://", "news:", "telnet://", "imap:", "rtsp://",
    "urn:", "pop:", "sip:", "sips:", "tftp:", "btspp://", "btl2cap://",
    "btgoep://", "tcpobex://", "irdaobex://", "file://", "urn:epc:id:",
    "urn:epc:tag:", "urn:epc:pat:", "urn:epc:raw:", "urn:epc:", "urn:nfc:",
]

NTAG_SIZES = {
    0x06: ("Ultralight EV1 (MF0UL11)", 20),
    0x12: ("NTAG213 / Ultralight EV1 (MF0UL21)", 45),
    0x3E: ("NTAG215", 135),
    0x6D: ("NTAG216", 231),
}

# NDEF data always starts at page 4 on these tags; pages 0-3 are UID,
# lock bytes and the capability container.
FIRST_DATA_PAGE = 4

LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "last_write.txt")


class Tee:
    """Mirror output to a log file so results survive a closing console."""

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


# ------------------------------------------------------- NDEF encoding ------
def build_uri_payload(url):
    """Compress the scheme into a one-byte prefix code where possible."""
    best_index, best_prefix = 0x00, ""
    for index, prefix in enumerate(URI_PREFIXES):
        if index and prefix and url.startswith(prefix) and len(prefix) > len(best_prefix):
            best_index, best_prefix = index, prefix
    return bytes([best_index]) + url[len(best_prefix):].encode("utf-8"), best_prefix


def build_vcard(name, phone, email, website, org, title):
    """A vCard 3.0 card. The spec wants CRLF line endings."""
    parts = name.split()
    given = parts[0] if parts else ""
    family = " ".join(parts[1:]) if len(parts) > 1 else ""

    lines = ["BEGIN:VCARD", "VERSION:3.0",
             "N:%s;%s;;;" % (family, given), "FN:%s" % name]
    if org:
        lines.append("ORG:%s" % org)
    if title:
        lines.append("TITLE:%s" % title)
    if phone:
        lines.append("TEL;TYPE=CELL:%s" % phone)
    if email:
        lines.append("EMAIL;TYPE=INTERNET:%s" % email)
    if website:
        lines.append("URL:%s" % website)
    lines.append("END:VCARD")
    return "\r\n".join(lines) + "\r\n"


def wrap_tlv(record_bytes):
    """Put an assembled NDEF message into the Type 2 tag's TLV container."""
    if len(record_bytes) < 0xFF:
        tlv = bytes([0x03, len(record_bytes)]) + record_bytes + b"\xFE"
    else:
        tlv = (bytes([0x03, 0xFF]) + len(record_bytes).to_bytes(2, "big")
               + record_bytes + b"\xFE")
    if len(tlv) % 4:
        tlv += b"\x00" * (4 - len(tlv) % 4)
    return tlv


def build_vcard_message(vcard_text):
    """A single MIME 'text/vcard' record. Android imports this straight into
    Contacts; iPhone background scanning ignores MIME records entirely."""
    payload = vcard_text.encode("utf-8")
    mime = b"text/vcard"
    header = 0xD2 if len(payload) < 256 else 0xC2  # MB+ME+SR(+/-), TNF=2 (MIME)
    if len(payload) < 256:
        record = bytes([header, len(mime), len(payload)]) + mime + payload
    else:
        record = (bytes([header, len(mime)]) + len(payload).to_bytes(4, "big")
                  + mime + payload)
    return wrap_tlv(record), record


def build_ndef_message(url):
    payload, prefix = build_uri_payload(url)

    # Record header: MB + ME + SR, TNF = 1 (NFC Forum well-known), type 'U'.
    if len(payload) < 256:
        record = bytes([0xD1, 0x01, len(payload), 0x55]) + payload
    else:
        record = (bytes([0xC1, 0x01]) + len(payload).to_bytes(4, "big")
                  + bytes([0x55]) + payload)

    # Wrap the record in the Type 2 tag's TLV container.
    if len(record) < 0xFF:
        tlv = bytes([0x03, len(record)]) + record + b"\xFE"
    else:
        tlv = (bytes([0x03, 0xFF]) + len(record).to_bytes(2, "big")
               + record + b"\xFE")

    # Tag memory is written a whole 4-byte page at a time.
    if len(tlv) % 4:
        tlv += b"\x00" * (4 - len(tlv) % 4)
    return tlv, record, payload, prefix


# ------------------------------------------------------------ card I/O ------
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

    def read_page(self, page):
        data, _, _ = self.send([0xFF, 0xB0, 0x00, page, 0x10])
        return data if self.ok() else None

    def read_single(self, page):
        """Read one 4-byte page; None if the tag refuses (past end of memory)."""
        try:
            data, _, _ = self.send([0xFF, 0xB0, 0x00, page, 0x04])
            return data[:4] if self.ok() and len(data) >= 4 else None
        except CardConnectionException:
            return None

    def uid(self):
        """UID straight from the reader - independent of any page read."""
        data, _, _ = self.send([0xFF, 0xCA, 0x00, 0x00, 0x00])
        return data if self.ok() else None

    def write_page(self, page, four_bytes, attempts=3):
        """Write one page, surviving the card reset a bump causes."""
        for attempt in range(attempts):
            try:
                self.send([0xFF, 0xD6, 0x00, page, 0x04] + list(four_bytes))
                if self.ok():
                    return True
            except CardConnectionException:
                pass
            if attempt < attempts - 1:
                print("    page %d: retrying after card reset..." % page)
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
    """Find the tag's real size by locating the highest readable page.

    Never guess this: the capability container is one-time-programmable, so a
    wrong size written into it cannot be taken back.
    """
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


# Page count -> (model, standard capability-container size byte).
MODELS_BY_PAGES = {
    20:  ("Ultralight EV1 (MF0UL11)", 0x06),
    41:  ("Ultralight EV1 (MF0UL21)", 0x12),
    45:  ("NTAG213", 0x12),
    135: ("NTAG215", 0x3E),
    231: ("NTAG216", 0x6D),
}


def read_header_verified(card, tries=4):
    """Read pages 0-3 until two consecutive reads agree and the UID matches
    the reader's own view. A single read can come back as garbage."""
    reader_uid = card.uid()
    previous = None
    for _ in range(tries):
        header = card.read_page(0)
        if header and len(header) >= 16:
            page_uid = header[0:3] + header[4:8]
            consistent = (previous is not None and header == previous)
            uid_matches = (reader_uid is None or page_uid == list(reader_uid))
            if consistent and uid_matches:
                return header
            previous = header
        time.sleep(0.05)
    return None


def pick_reader(hint="PICC"):
    found = readers()
    if not found:
        sys.exit("No PC/SC readers found. Is the ACR1552U plugged in?")
    for r in found:
        if hint.lower() in str(r).lower():
            return r
    return found[0]


def wait_for_card(reader):
    print("Present the card to the reader...")
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


def decode_uri_record(data):
    """Pull a URI back out of a tag dump, to prove what was written."""
    i = 0
    while i < len(data):
        if data[i] == 0x00:
            i += 1
            continue
        if data[i] == 0xFE or i + 1 >= len(data):
            return None
        tag, length = data[i], data[i + 1]
        i += 2
        if length == 0xFF:
            length = (data[i] << 8) | data[i + 1]
            i += 2
        if tag == 0x03:
            rec = data[i:i + length]
            if len(rec) >= 5 and rec[3] == 0x55:
                payload = rec[4:4 + rec[2]]
                prefix = URI_PREFIXES[payload[0]] if payload[0] < len(URI_PREFIXES) else ""
                return prefix + payload[1:].decode("utf-8", "replace")
            return None
        i += length
    return None


# ---------------------------------------------------------------- main ------
def main():
    ap = argparse.ArgumentParser(description="Write a URL to an NFC tag.")
    ap.add_argument("url", nargs="?", default=DEFAULT_URL,
                    help="URL to write (default: %s)" % DEFAULT_URL)
    ap.add_argument("--verify-only", action="store_true",
                    help="read the tag and show its URL without writing")
    ap.add_argument("--uid", metavar="HEX",
                    help="only write if the tag's UID matches, e.g. 0405A2377E6180")
    ap.add_argument("--force", action="store_true",
                    help="write even if the tag holds unrecognised existing data")
    ap.add_argument("--vcard", action="store_true",
                    help="write contact details as a vCard (Android only - "
                         "iPhone ignores vCard records on tags)")
    ap.add_argument("--name", default="", help="vCard: full name")
    ap.add_argument("--phone", default="", help="vCard: phone number")
    ap.add_argument("--email", default="", help="vCard: email address")
    ap.add_argument("--website", default="", help="vCard: website URL")
    ap.add_argument("--org", default="", help="vCard: company")
    ap.add_argument("--title", default="", help="vCard: job title")
    args = ap.parse_args()

    if args.vcard:
        if not args.name:
            sys.exit("--vcard needs at least --name")
        vcard_text = build_vcard(args.name, args.phone, args.email,
                                 args.website, args.org, args.title)
        tlv, record = build_vcard_message(vcard_text)

        # Save the same card as a .vcf, which is what you host behind a URL
        # for the iPhone-compatible version of this tag.
        vcf_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "contact.vcf")
        with open(vcf_path, "w", encoding="utf-8", newline="") as handle:
            handle.write(vcard_text)

        print("Writing vCard:")
        for line in vcard_text.strip().splitlines():
            print("    %s" % line)
        print("\nAlso saved    : %s" % vcf_path)
        print("Record type   : MIME text/vcard")
        print("WARNING       : iPhone ignores vCard records on NFC tags.")
        print("                Host contact.vcf and write its URL instead.")
    else:
        tlv, record, payload, prefix = build_ndef_message(args.url)
        print("URL to write : %s" % args.url)
        print("Prefix code  : 0x%02X (%s)"
              % (payload[0], prefix if prefix else "no compression"))
        print("NDEF record  : %s" % hexs(record))

    print("Bytes to tag : %d (%d pages, starting at page %d)"
          % (len(tlv), len(tlv) // 4, FIRST_DATA_PAGE))

    reader = pick_reader()
    print("\nUsing reader : %s\n" % reader)

    card = wait_for_card(reader)
    try:
        header = read_header_verified(card)
        if not header:
            banner("CANNOT READ TAG RELIABLY",
                   "Pages 0-3 did not read back consistently. Try re-tapping.")
            return

        total_pages = probe_page_count(card)
        model, standard_cc = MODELS_BY_PAGES.get(total_pages, (None, None))
        cc = header[12:16]
        print("Tag          : %s (%d pages)"
              % (model if model else "unrecognised tag", total_pages))
        print("UID          : %s" % hexs(header[0:3] + header[4:8]))
        print("Capability   : %s" % hexs(cc))

        if cc[0] != 0xE1:
            # The capability container is one-time-programmable. Only write it
            # when the probe has established what the tag actually is.
            if standard_cc is None:
                banner("WILL NOT FORMAT",
                       "Unrecognised tag (%d pages) - refusing to guess." % total_pages)
                return
            print("\nTag is not NDEF-formatted; writing %s container E1 10 %02X 00."
                  % (model, standard_cc))
            if not card.write_page(3, [0xE1, 0x10, standard_cc, 0x00]):
                banner("FORMAT FAILED", "Could not write the capability container.")
                return
            cc = [0xE1, 0x10, standard_cc, 0x00]

        capacity = cc[2] * 8
        print("Usable space : %d bytes" % capacity)
        if cc[3]:
            banner("TAG IS READ-ONLY", "This tag has been locked and cannot be written.")
            return
        if len(tlv) > capacity:
            banner("URL TOO LONG",
                   "Needs %d bytes but the tag holds %d." % (len(tlv), capacity))
            return

        # Refuse the wrong card outright when the caller named a UID.
        if args.uid:
            wanted = args.uid.replace(" ", "").replace(":", "").upper()
            actual = "".join("%02X" % b for b in (card.uid() or []))
            if wanted != actual:
                banner("WRONG CARD - NOTHING WRITTEN",
                       "Tag is %s, expected %s" % (actual, wanted))
                return

        # An unformatted tag carrying non-zero data is somebody's existing card,
        # not a blank. Do not silently overwrite it.
        if cc[0] != 0xE1 and not args.force:
            existing = []
            for page in range(FIRST_DATA_PAGE, min(FIRST_DATA_PAGE + 4, total_pages)):
                chunk = card.read_single(page)
                if chunk and any(chunk):
                    existing.append((page, chunk))
            if existing:
                banner("TAG HOLDS UNRECOGNISED DATA",
                       "Not NDEF-formatted, but not blank either.")
                for page, chunk in existing:
                    print("    page %3d | %s" % (page, hexs(chunk)))
                print("\n  This looks like an existing card, not a blank tag.")
                print("  Back it up first:   python nfc_backup.py")
                print("  Then force with:    python nfc_write.py --force")
                return

        if args.verify_only:
            print("\n(--verify-only: not writing)")
        else:
            print("\nWriting...")
            for offset in range(0, len(tlv), 4):
                page = FIRST_DATA_PAGE + offset // 4
                chunk = tlv[offset:offset + 4]
                if not card.write_page(page, chunk):
                    banner("WRITE FAILED",
                           "Page %d refused (SW %02X%02X)." % (page, card.sw[0], card.sw[1]))
                    return
                print("  page %3d <- %s" % (page, hexs(chunk)))
                # The reader resets the card if writes are issued back to back;
                # a short gap between pages keeps the session alive.
                time.sleep(0.05)

        # Read the tag back and decode it, rather than trusting the writes.
        print("\nVerifying by reading the tag back...")
        try:
            card.reconnect()  # fresh session, so verification is independent
        except Exception:
            pass
        read_back = bytearray()
        page = FIRST_DATA_PAGE
        while len(read_back) < len(tlv):
            try:
                data = card.read_page(page)
            except CardConnectionException:
                card.reconnect()
                continue
            if not data:
                break
            read_back.extend(data)
            page += 4
        del read_back[len(tlv):]

        # Compare the actual bytes, which works for any record type.
        matches = bytes(read_back) == tlv
        if args.vcard:
            print("  bytes match : %s" % ("yes" if matches else "NO"))
            if matches:
                banner("SUCCESS - VCARD WRITTEN",
                       "Android: tap to add contact. iPhone: see note above.")
            else:
                banner("VERIFY FAILED", "Tag contents differ from what was sent.")
        else:
            url_on_tag = decode_uri_record(bytes(read_back))
            print("  raw bytes  : %s" % hexs(read_back))
            print("  decoded    : %s" % url_on_tag)
            if url_on_tag == args.url:
                banner("SUCCESS - TAG READY",
                       "Tap it with a phone and it will open %s" % args.url)
            else:
                banner("VERIFY FAILED",
                       "Tag holds %r, expected %r" % (url_on_tag, args.url))
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
