using Iot.Device.Card;

namespace NfcBattler.Cards;

// Adapts the commands used by Microsoft's UltralightCard to the ACR1552U.
public sealed class PcscTransceiver(Func<byte[], byte[]> exchange) : CardTransceiver
{
    public override uint MaximumReadSize => 16;
    public override uint MaximumWriteSize => 4;

    public override bool ReselectTarget(byte targetNumber) => false;

    public byte[] Exchange(byte[] command)
    {
        byte[] response = exchange(command);
        if (response.Length < 2)
            throw new IOException("The reader returned an incomplete response.");
        if (response[^2] != 0x90 || response[^1] != 0x00)
            throw new IOException($"The reader rejected the command (status {response[^2]:X2}{response[^1]:X2}). Keep the card on the reader; it may be locked or unsupported.");
        return response[..^2];
    }

    public override int Transceive(byte targetNumber, ReadOnlySpan<byte> dataToSend,
        Span<byte> dataFromCard, NfcProtocol protocol)
    {
        byte[] command;
        if (dataToSend.Length == 2 && dataToSend[0] == 0x30)
        {
            command = [0xFF, 0xB0, 0x00, dataToSend[1], 0x10];
        }
        else if (dataToSend.Length == 6 && dataToSend[0] == 0xA2)
        {
            // Never allow a library call to write identity, lock, or configuration pages.
            if (dataToSend[1] < 4 || dataToSend[1] > 129)
                throw new IOException("Writes are restricted to NTAG215 user pages 4-129.");
            command = [0xFF, 0xD6, 0x00, dataToSend[1], 0x04, .. dataToSend[2..]];
        }
        else if (dataToSend.Length == 1 && dataToSend[0] == 0x60)
        {
            // ACR1552U reference manual, section 5.3.4.1.
            command = [0xFF, 0x00, 0x00, 0x00, 0x01, 0x60];
        }
        else
        {
            throw new NotSupportedException("This adapter supports READ, WRITE, and GET_VERSION only.");
        }

        byte[] payload = Exchange(command);
        if (payload.Length != dataFromCard.Length)
            throw new IOException($"Expected {dataFromCard.Length} response bytes, received {payload.Length}. GET_VERSION may require updated ACR1552U firmware; no write has been verified.");
        payload.CopyTo(dataFromCard);
        return payload.Length;
    }
}
