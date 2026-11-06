using Iot.Device.Card.Ultralight;
using Iot.Device.Ndef;
using NfcBattler.Core;

namespace NfcBattler.Cards;

public sealed class CharacterCardStore(UltralightCard card)
{
    // Null means genuinely blank, not an unreadable or unrelated save.
    public Character? Load()
    {
        byte[] memory = ReadMemory();
        if (memory.All(b => b == 0)) return null;
        if (memory.AsSpan(0, 4).SequenceEqual(new byte[] { 3, 0, 0xFE, 0 }) &&
            memory.AsSpan(4).ToArray().All(b => b == 0)) return null;

        try
        {
            // Parse the TLVs explicitly so a malformed record cannot be treated as blank.
            int offset = 0;
            while (offset < memory.Length)
            {
                byte tag = memory[offset++];
                if (tag == 0) continue;
                if (tag == 0xFE) break;
                if (offset >= memory.Length) throw new InvalidDataException("Truncated TLV.");
                int length = memory[offset++];
                if (length == 255)
                {
                    if (offset + 2 > memory.Length) throw new InvalidDataException("Truncated TLV length.");
                    length = memory[offset] * 256 + memory[offset + 1];
                    offset += 2;
                }
                if (offset + length > memory.Length) throw new InvalidDataException("Truncated NDEF data.");
                if (tag == 3 && length > 0)
                {
                    var message = new NdefMessage(memory.AsSpan(offset, length));
                    var saves = message.Records.Where(r => MediaRecord.IsMediaRecord(r) &&
                        new MediaRecord(r).PayloadType == CharacterSaveCodec.MimeType).ToArray();
                    if (saves.Length != 1)
                        throw new InvalidDataException("The card does not contain exactly one character save. Clear it before creating a character.");
                    return CharacterSaveCodec.Decode(saves[0].Payload ?? []);
                }
                offset += length;
            }
        }
        catch (Exception ex) when (ex is ArgumentException or IndexOutOfRangeException or OverflowException)
        {
            throw new InvalidDataException("The card contains malformed data. It will not be overwritten.", ex);
        }
        throw new InvalidDataException("The card contains other or incomplete data. Clear it before creating a character.");
    }

    public void Create(Character character)
    {
        byte[] payload = CharacterSaveCodec.Encode(character);
        if (Load() is not null)
            throw new InvalidOperationException("This card already has a character. It cannot be replaced.");
        card.BlockNumber = 3;
        card.Command = UltralightCommand.Read16Bytes;
        if (card.RunUltralightCommand() != 16 || card.Data[0] != 0xE1 || card.Data[1] != 0x10 ||
            card.Data[2] != 0x3E || card.Data[3] != 0)
            throw new IOException("Character creation requires an already formatted, writable NTAG215.");
        var message = new NdefMessage();
        message.Records.Add(new MediaRecord(CharacterSaveCodec.MimeType, payload));
        if (!card.WriteNdefMessage(message)) throw new IOException("Character write failed. Read the card before retrying.");
        var actual = Load();
        if (actual is null || !CharacterSaveCodec.Encode(actual).SequenceEqual(payload))
            throw new IOException("Character write could not be verified.");
    }

    private byte[] ReadMemory()
    {
        byte[] memory = new byte[504];
        for (int offset = 0; offset < memory.Length; offset += 16)
        {
            int page = Math.Min(4 + offset / 4, 126);
            card.BlockNumber = (byte)page;
            card.Command = UltralightCommand.Read16Bytes;
            if (card.RunUltralightCommand() != 16) throw new IOException("Could not read the card. No creation will be attempted.");
            int start = (4 + offset / 4 - page) * 4;
            card.Data.AsSpan(start, Math.Min(16 - start, memory.Length - offset)).CopyTo(memory.AsSpan(offset));
        }
        return memory;
    }
}
