using Iot.Device.Card.Ultralight;

namespace NfcBattler.Cards;

public static class Ntag215Tools
{
    public static void Clear(UltralightCard card)
    {
        if (card.UltralightCardType != UltralightCardType.UltralightNtag215)
            throw new NotSupportedException("Only NTAG215 cards can be cleared.");

        card.BlockNumber = 3;
        card.Command = UltralightCommand.Read16Bytes;
        if (card.RunUltralightCommand() != 16)
            throw new IOException("Could not read the card's formatting. Nothing was cleared.");
        if (card.Data[0] != 0xE1 || card.Data[1] != 0x10 || card.Data[2] != 0x3E || card.Data[3] != 0)
            throw new IOException("Clear requires an already NDEF-formatted, writable NTAG215.");

        byte[] expected = new byte[504];
        // An empty NDEF message followed by a terminator; erase residual data too.
        expected[0] = 0x03;
        expected[2] = 0xFE;
        for (int page = 4; page <= 129; page++)
        {
            card.BlockNumber = (byte)page;
            card.Command = UltralightCommand.Write4Bytes;
            card.Data = expected.AsSpan((page - 4) * 4, 4).ToArray();
            if (card.RunUltralightCommand() < 0)
                throw new IOException("Clear failed. The card may be partly cleared; read it before trying again.");
        }

        for (int offset = 0; offset < expected.Length; offset += 16)
        {
            int page = Math.Min(4 + offset / 4, 126);
            card.BlockNumber = (byte)page;
            card.Command = UltralightCommand.Read16Bytes;
            if (card.RunUltralightCommand() != 16)
                throw new IOException("Clear could not be verified. Read the card before trying again.");
            int sourceOffset = (4 + offset / 4 - page) * 4;
            int count = Math.Min(16 - sourceOffset, expected.Length - offset);
            if (!card.Data.AsSpan(sourceOffset, count).SequenceEqual(expected.AsSpan(offset, count)))
                throw new IOException("Clear verification failed: some user data remains. Read the card before trying again.");
        }
    }
}
