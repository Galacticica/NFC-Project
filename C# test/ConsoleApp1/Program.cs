/*
 * File: Program.cs
 * Project: ConsoleApp1
 * Created Date: 2026-09-26
 * Author: Reagan Zierke
 * Email: reaganzierke@gmail.com
 * -----
 * Last Modified: 2026-09-26 21:05:56
 * Modified By: Reagan Zierke
 * -----
 * Description: <<description>>
 */

using System.Text;
using PCSC;
using PCSC.Exceptions;

Console.Write("Enter a command (read/write/clear): ");
string? input = Console.ReadLine()?.Trim().ToLower();

if (input == "read")
{
    ReadCard();
}
else if (input == "write")
{
    Console.WriteLine("Writing card...");
}
else
{
    Console.WriteLine($"Unknown command: {input}");
}

// Read an NTAG / MIFARE Ultralight tag: print its UID, the raw pages and any
// URL or text stored on it.
static void ReadCard()
{
    using var context = ContextFactory.Instance.Establish(SCardScope.System);
    string[] readers = context.GetReaders();
    if (readers.Length == 0)
    {
        Console.WriteLine("No NFC reader found. Is it plugged in?");
        return;
    }
    Console.WriteLine($"Using reader: {readers[0]}");

    ICardReader reader;
    try
    {
        reader = context.ConnectReader(readers[0], SCardShareMode.Shared, SCardProtocol.Any);
    }
    catch (PCSCException)
    {
        Console.WriteLine("No card on the reader. Place a card on it and try again.");
        return;
    }

    using (reader)
    {
        // FF CA 00 00 00 = "get UID" (a PC/SC command the reader handles itself)
        byte[]? uid = Send(reader, [0xFF, 0xCA, 0x00, 0x00, 0x00]);
        Console.WriteLine($"UID        : {(uid == null ? "(failed)" : Convert.ToHexString(uid))}");

        // FF B0 00 <page> 10 = read 16 bytes (4 pages) starting at <page>.
        // Page 4 onwards is user data. It starts 03 <length>, so stop once we
        // have that many bytes rather than dumping the whole card.
        var data = new List<byte>();
        Console.WriteLine("\nPage | Hex         | Text");
        for (int page = 4; page < 44; page += 4)
        {
            byte[]? block = Send(reader, [0xFF, 0xB0, 0x00, (byte)page, 0x10]);
            if (block == null) break;

            for (int i = 0; i < 4; i++)
            {
                byte[] p = block[(i * 4)..(i * 4 + 4)];
                string text = new string(p.Select(b => b is >= 0x20 and < 0x7F ? (char)b : '.').ToArray());
                Console.WriteLine($"{page + i,4} | {Convert.ToHexString(p),-11} | {text}");
            }
            data.AddRange(block);
            if (data[0] != 0x03 || data.Count >= 2 + data[1]) break;
        }

        Console.WriteLine($"\nContents   : {DecodeNdef(data.ToArray())}");
    }
}

// Send a command to the card. Returns the response data, or null if the card
// did not answer with the "OK" status 90 00.
static byte[]? Send(ICardReader reader, byte[] command)
{
    var response = new byte[258];
    int length = reader.Transmit(command, response);
    if (length < 2 || response[length - 2] != 0x90 || response[length - 1] != 0x00)
        return null;
    return response[..(length - 2)];
}

// Pull a URL or text out of the first NDEF record. Handles the common case of
// one short record, which is what phones and most writing apps produce.
static string DecodeNdef(byte[] data)
{
    string[] uriPrefixes = ["", "http://www.", "https://www.", "http://", "https://", "tel:", "mailto:"];

    // Data starts with a TLV: 03 <length> <NDEF message>
    if (data.Length < 7 || data[0] != 0x03) return "(no NDEF data - card may be blank)";

    int header = data[2];
    int typeLength = data[3];
    int payloadLength = data[4];
    bool shortRecord = (header & 0x10) != 0;
    if (!shortRecord || typeLength != 1) return "(NDEF record type not supported by this simple reader)";

    char type = (char)data[5];
    byte[] payload = data[6..Math.Min(6 + payloadLength, data.Length)];
    if (payload.Length == 0) return "(empty record)";

    if (type == 'U')
    {
        string prefix = payload[0] < uriPrefixes.Length ? uriPrefixes[payload[0]] : "";
        return "URL: " + prefix + Encoding.UTF8.GetString(payload, 1, payload.Length - 1);
    }
    if (type == 'T')
    {
        int langLength = payload[0] & 0x3F;
        return "Text: " + Encoding.UTF8.GetString(payload, 1 + langLength, payload.Length - 1 - langLength);
    }
    return $"(record type '{type}' not supported by this simple reader)";
}
