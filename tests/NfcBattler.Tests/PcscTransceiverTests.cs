using System.Text;
using Iot.Device.Card;
using Iot.Device.Card.Ultralight;
using Iot.Device.Ndef;
using NfcBattler.Cards;
using Xunit;

namespace NfcBattler.Tests;

public class PcscTransceiverTests
{
    [Fact]
    public void ReadUsesPcscPageCommandAndRemovesStatusBytes()
    {
        var transceiver = new PcscTransceiver(command =>
        {
            Assert.Equal(new byte[] { 0xFF, 0xB0, 0, 4, 16 }, command);
            return [.. Enumerable.Range(0, 16).Select(i => (byte)i), 0x90, 0];
        });
        byte[] response = new byte[16];
        Assert.Equal(16, transceiver.Transceive(0, [0x30, 4], response, NfcProtocol.Iso14443_3));
        Assert.Equal(Enumerable.Range(0, 16).Select(i => (byte)i), response);
    }

    [Theory]
    [InlineData(0)]
    [InlineData(3)]
    [InlineData(130)]
    [InlineData(134)]
    [InlineData(255)]
    public void RefusesWritesOutsideUserMemory(int page)
    {
        var transceiver = new PcscTransceiver(_ => throw new Exception("Must not send any command"));
        Assert.Throws<IOException>(() => transceiver.Transceive(0,
            [0xA2, (byte)page, 1, 2, 3, 4], [], NfcProtocol.Iso14443_3));
    }

    [Fact]
    public void RefusesTruncatedGetVersionInsteadOfGuessingCardType()
    {
        var transceiver = new PcscTransceiver(_ => [0, 4, 4, 2, 1, 0x90, 0]);
        Assert.Throws<IOException>(() => new UltralightCard(transceiver, 0));
    }

    [Fact]
    public void RefusesFailedStatusEvenWhenResponseContainsData()
    {
        var transceiver = new PcscTransceiver(_ => [1, 2, 0x63, 0]);
        Assert.Throws<IOException>(() => transceiver.Exchange([0xFF, 0xCA, 0, 0, 0]));
    }

    [Theory]
    [InlineData("Hello, NFC!")]
    [InlineData("Unicode works: café 日本語")]
    [InlineData("long")]
    public void MicrosoftNdefLibraryRoundTripsTextThroughPcscAdapter(string text)
    {
        if (text == "long") text = new string('x', 300); // Extended TLV length and multiple reads.
        byte[] memory = new byte[540];
        var writtenPages = new List<byte>();
        var transceiver = new PcscTransceiver(command =>
        {
            if (command[1] == 0)
            {
                Assert.Equal(new byte[] { 0xFF, 0, 0, 0, 1, 0x60 }, command);
                return [0, 4, 4, 2, 1, 0, 0x11, 3, 0x90, 0];
            }
            if (command[1] == 0xB0)
                return [.. memory.AsSpan(command[3] * 4, 16).ToArray(), 0x90, 0];
            Assert.Equal(0xD6, command[1]);
            Assert.Equal(4, command[4]);
            writtenPages.Add(command[3]);
            command.AsSpan(5, 4).CopyTo(memory.AsSpan(command[3] * 4));
            return [0x90, 0];
        });
        var card = new UltralightCard(transceiver, 0);
        Assert.Equal(UltralightCardType.UltralightNtag215, card.UltralightCardType);
        var message = new NdefMessage();
        message.Records.Add(new TextRecord(text, "en", Encoding.UTF8));

        Assert.True(card.WriteNdefMessage(message));
        Assert.True(card.TryReadNdefMessage(out var actual));
        Assert.Equal(text, new TextRecord(Assert.Single(actual.Records)).Text);
        Assert.NotEmpty(writtenPages);
        Assert.All(writtenPages, page => Assert.InRange(page, 4, 129));
        Assert.All(memory[..16], value => Assert.Equal(0, value));
        Assert.All(memory[520..], value => Assert.Equal(0, value));
    }
}
