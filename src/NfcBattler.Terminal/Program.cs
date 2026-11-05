using Iot.Device.Ndef;
using NfcBattler.Cards;
using PCSC.Exceptions;

Console.WriteLine("Welcome to NFC Card Battler!");

while (true)
{
    Console.WriteLine("\n1. Read an NFC card\n2. Write text to an NFC card\n3. Clear an NFC card\n0. Exit");
    Console.Write("Choose an option: ");
    string? choice = Console.ReadLine()?.Trim();
    if (choice is null or "0") break;
    if (choice is not ("1" or "2" or "3"))
    {
        Console.WriteLine("Enter 1, 2, 3, or 0.");
        continue;
    }

    try
    {
        string[] readers = NfcCardSession.GetReaders()
            .Where(name => !name.Contains("SAM", StringComparison.OrdinalIgnoreCase)).ToArray();
        if (readers.Length == 0)
        {
            Console.WriteLine("No contactless reader found. Plug in your ACS ACR1552U and try again.");
            continue;
        }

        int selected = 0;
        if (readers.Length > 1)
        {
            for (int i = 0; i < readers.Length; i++) Console.WriteLine($"{i + 1}. {readers[i]}");
            Console.Write("Select a reader (Enter to cancel): ");
            if (!int.TryParse(Console.ReadLine(), out int number) || number < 1 || number > readers.Length)
                continue;
            selected = number - 1;
        }

        string? text = null;
        if (choice == "2")
        {
            Console.Write("Text to write (Enter to cancel): ");
            text = Console.ReadLine();
            if (string.IsNullOrWhiteSpace(text)) continue;
        }

        Console.WriteLine($"Reader: {readers[selected]}");
        Console.Write("Place an NTAG215 card on the reader, keep it there, and press Enter (or type cancel): ");
        string? ready = Console.ReadLine();
        if (ready is null || ready.Trim().Equals("cancel", StringComparison.OrdinalIgnoreCase)) continue;

        using var session = new NfcCardSession(readers[selected]);
        Console.WriteLine($"UID: {session.Uid} | Type: NTAG215");
        var message = session.ReadMessage();
        if (message is null) Console.WriteLine("No readable NDEF message found.");
        else foreach (var record in message.Records)
        {
            if (TextRecord.IsTextRecord(record)) Console.WriteLine($"Text: {new TextRecord(record).Text}");
            else if (UriRecord.IsUriRecord(record)) Console.WriteLine($"URL: {new UriRecord(record).FullUri}");
            else Console.WriteLine($"Record payload (hex): {Convert.ToHexString(record.Payload ?? [])}");
        }

        if (choice == "1")
        {
            byte[] memory = session.ReadUserMemory();
            for (int offset = 0; offset < memory.Length; offset += 4)
                Console.WriteLine($"Page {4 + offset / 4,3}: {Convert.ToHexString(memory.AsSpan(offset, 4))}");
        }
        else if (choice == "2")
        {
            Console.WriteLine($"New text: {text}");
            Console.Write("Replace this card's NDEF content? Type WRITE to confirm: ");
            if (Console.ReadLine() != "WRITE")
            {
                Console.WriteLine("Write cancelled.");
                continue;
            }
            session.WriteText(text!);
            Console.WriteLine("Written and verified successfully.");
        }
        else
        {
            Console.Write("Erase all user data on this card? Type CLEAR to confirm: ");
            if (Console.ReadLine() != "CLEAR")
            {
                Console.WriteLine("Clear cancelled.");
                continue;
            }
            session.Clear();
            Console.WriteLine("Cleared and verified successfully.");
        }
    }
    catch (Exception ex) when (ex is PCSCException or IOException or ArgumentException or NotSupportedException or InvalidOperationException)
    {
        Console.WriteLine($"NFC operation failed: {ex.Message}");
        Console.WriteLine("Keep the card on the reader and retry. If no card is present, place one first.");
    }
}
