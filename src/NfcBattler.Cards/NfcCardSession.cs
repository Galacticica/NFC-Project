using System.Text;
using Iot.Device.Card.Ultralight;
using Iot.Device.Ndef;
using PCSC;

namespace NfcBattler.Cards;

// Owns one reader connection. No game save or PC-side database is involved.
public sealed class NfcCardSession : IDisposable
{
    private readonly ISCardContext context;
    private readonly ICardReader reader;
    private readonly PcscTransceiver transceiver;
    private readonly UltralightCard card;

    public string Uid { get; }

    public static string[] GetReaders()
    {
        using var context = ContextFactory.Instance.Establish(SCardScope.System);
        return context.GetReaders();
    }

    public NfcCardSession(string readerName)
    {
        context = ContextFactory.Instance.Establish(SCardScope.System);
        try
        {
            reader = context.ConnectReader(readerName, SCardShareMode.Exclusive, SCardProtocol.Any);
            transceiver = new PcscTransceiver(command =>
            {
                byte[] response = new byte[258];
                int length = reader.Transmit(command, response);
                return response[..length];
            });
            Uid = Convert.ToHexString(transceiver.Exchange([0xFF, 0xCA, 0, 0, 0]));
            card = new UltralightCard(transceiver, 0);
            if (card.UltralightCardType != UltralightCardType.UltralightNtag215)
                throw new NotSupportedException($"Detected {card.UltralightCardType}. This version supports NTAG215 cards only.");
        }
        catch
        {
            reader?.Dispose();
            context.Dispose();
            throw;
        }
    }

    public byte[] ReadUserMemory()
    {
        byte[] memory = new byte[504];
        // Last read starts at 126 so it stops at page 129, before configuration.
        for (int offset = 0; offset < memory.Length; offset += 16)
        {
            int page = Math.Min(4 + offset / 4, 126);
            byte[] data = ReadPages((byte)page);
            int sourceOffset = (4 + offset / 4 - page) * 4;
            data.AsSpan(sourceOffset, Math.Min(16 - sourceOffset, memory.Length - offset))
                .CopyTo(memory.AsSpan(offset));
        }
        return memory;
    }

    public NdefMessage? ReadMessage() => card.TryReadNdefMessage(out var message) ? message : null;

    public void Clear() => Ntag215Tools.Clear(card);

    public NfcBattler.Core.Character? LoadCharacter() => new CharacterCardStore(card).Load();

    public void CreateCharacter(NfcBattler.Core.Character character) => new CharacterCardStore(card).Create(character);

    public void WriteText(string text)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(text);
        byte[] cc = ReadPages(3);
        if (cc[0] != 0xE1 || cc[1] != 0x10 || cc[2] != 0x3E || cc[3] != 0)
            throw new IOException("The card must already be NDEF formatted and writable. This tool does not change formatting or protection settings.");

        var message = new NdefMessage();
        message.Records.Add(new TextRecord(text, "en", Encoding.UTF8));
        int storedLength = message.Length + (message.Length > 254 ? 5 : 3);
        if ((storedLength + 3) / 4 * 4 > 496)
            throw new ArgumentException("That text is too long for this card. Try a shorter message.");

        // Protect future game saves: generic text writing must never replace one.
        var existing = ReadMessage();
        if (existing?.Records.Any(record => MediaRecord.IsMediaRecord(record)
            && new MediaRecord(record).PayloadType == "application/x-nfcbattler") == true)
            throw new IOException("This card contains a game save. Text writing cannot replace it.");

        if (!card.WriteNdefMessage(message))
            throw new IOException("Write failed. Keep the card on the reader and try reading it again.");
        var actual = ReadMessage();
        if (actual is null || !Serialize(message).SequenceEqual(Serialize(actual)))
            throw new IOException("The write could not be verified. Read the card before trying again.");
    }

    private byte[] ReadPages(byte page)
    {
        byte[] data = new byte[16];
        transceiver.Transceive(0, [0x30, page], data, Iot.Device.Card.NfcProtocol.Iso14443_3);
        return data;
    }

    private static byte[] Serialize(NdefMessage message)
    {
        byte[] data = new byte[message.Length];
        message.Serialize(data);
        return data;
    }

    public void Dispose()
    {
        reader.Dispose();
        context.Dispose();
    }
}
