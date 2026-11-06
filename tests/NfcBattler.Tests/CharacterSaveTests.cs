using Iot.Device.Card.Ultralight;
using Iot.Device.Ndef;
using NfcBattler.Cards;
using NfcBattler.Core;
using Xunit;

namespace NfcBattler.Tests;

public class CharacterSaveTests
{
    [Fact]
    public void CodecMatchesLayoutAndPreservesSeparateMoveIdsAndBitmap()
    {
        var character = new Character("Ember")
        {
            ClassId = 4, Level = 255, Experience = uint.MaxValue, Money = 0x12345678,
            UnusedStatPoints = 9, MaxHealth = 500, Attack = 600, Defense = 700,
            Speed = 800, Magic = 900, Luck = 1000,
            Move1 = 254, Move2 = null, Move3 = 0, Move4 = 2
        };
        character.UnlockedMovesBitmap[15] = 128; // Bitmap 127 maps to move 254.
        byte[] bytes = CharacterSaveCodec.Encode(character);
        Assert.Equal(64, bytes.Length);
        Assert.Equal(new byte[] { (byte)'N', (byte)'B', 1, 4, 255 }, bytes[..5]);
        Assert.Equal(new byte[] { 0x78, 0x56, 0x34, 0x12 }, bytes[9..13]);
        Assert.Equal(new byte[] { 254, 255, 0, 2 }, bytes[26..30]);
        Assert.Equal(128, bytes[57]);
        Assert.Equal(System.Text.Encoding.ASCII.GetBytes("Ember\0"), bytes[30..36]);
        Assert.Equal(character.UnlockedMovesBitmap, bytes[42..58]);
        Assert.All(bytes[58..], value => Assert.Equal(0, value));
        var actual = CharacterSaveCodec.Decode(bytes);
        Assert.Equal(bytes, CharacterSaveCodec.Encode(actual));
        Assert.Null(actual.Move2);
        Assert.Equal(500, actual.Health);
    }

    [Theory]
    [InlineData("")]
    [InlineData("TwelveChars!")]
    [InlineData("Ember🔥")]
    public void CodecRejectsNamesThatCannotFitLayout(string name)
        => Assert.Throws<ArgumentException>(() => CharacterSaveCodec.Encode(new Character(name)));

    [Fact]
    public void CodecRejectsUnsupportedVersionAndInvalidMarker()
    {
        byte[] bytes = CharacterSaveCodec.Encode(new Character("Ember"));
        bytes[2] = 2;
        Assert.Throws<InvalidDataException>(() => CharacterSaveCodec.Decode(bytes));
        bytes[2] = CharacterSaveCodec.CurrentVersion;
        bytes[0] = 0;
        Assert.Throws<InvalidDataException>(() => CharacterSaveCodec.Decode(bytes));
    }

    [Fact]
    public void CodecRejectsNumericOverflowRatherThanTruncating()
        => Assert.Throws<OverflowException>(() => CharacterSaveCodec.Encode(new Character("Ember") { Level = 256 }));

    [Fact]
    public void CodecPreservesAllLockedBitmapAndLongestName()
    {
        var character = new Character("ABCDEFGHIJK") { UnlockedMovesBitmap = new byte[16] };
        byte[] data = CharacterSaveCodec.Encode(character);
        Assert.Equal(0, data[41]);
        Assert.All(data[42..58], value => Assert.Equal(0, value));
        Assert.Equal(character.Name, CharacterSaveCodec.Decode(data).Name);
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public void CreatesAndLoadsOnBlankCardsWithoutTouchingProtectedPages(bool emptyNdef)
    {
        var fake = new FakeCard();
        if (emptyNdef) new byte[] { 3, 0, 0xFE, 0 }.CopyTo(fake.Memory, 16);
        byte[] protectedPages = fake.Memory[..16];
        var store = new CharacterCardStore(fake.Card);
        Assert.Null(store.Load());
        store.Create(new Character("Ember") { Move1 = 254 });
        var actual = Assert.IsType<Character>(store.Load());
        Assert.Equal("Ember", actual.Name);
        Assert.Equal((byte)254, actual.Move1);
        Assert.Null(actual.Move2);
        Assert.Equal(protectedPages, fake.Memory[..16]);
        Assert.All(fake.WrittenPages, page => Assert.InRange(page, 4, 129));
    }

    [Fact]
    public void CreationNeverReplacesExistingCharacter()
    {
        var fake = new FakeCard();
        var store = new CharacterCardStore(fake.Card);
        store.Create(new Character("Ember"));
        fake.WrittenPages.Clear();
        Assert.Throws<InvalidOperationException>(() => store.Create(new Character("Other")));
        Assert.Empty(fake.WrittenPages);
        Assert.Equal("Ember", store.Load()!.Name);
    }

    [Fact]
    public void UnrelatedAndMalformedDataAreNotBlank()
    {
        var fake = new FakeCard();
        var message = new NdefMessage();
        message.Records.Add(new TextRecord("old content", "en", System.Text.Encoding.UTF8));
        Assert.True(fake.Card.WriteNdefMessage(message));
        fake.WrittenPages.Clear();
        var store = new CharacterCardStore(fake.Card);
        Assert.Throws<InvalidDataException>(() => store.Create(new Character("Ember")));
        Assert.Empty(fake.WrittenPages);
        fake.Memory[16] = 3;
        fake.Memory[17] = 255;
        fake.Memory[18] = 255;
        fake.Memory[19] = 255;
        Assert.Throws<InvalidDataException>(() => store.Load());
    }

    [Fact]
    public void CreationDetectsWriteThatDidNotReachCard()
    {
        var fake = new FakeCard { IgnoreWrites = true };
        Assert.Throws<IOException>(() => new CharacterCardStore(fake.Card).Create(new Character("Ember")));
    }

    [Theory]
    [InlineData(0u)]
    [InlineData(1u)]
    [InlineData(0x12345678u)]
    [InlineData(uint.MaxValue)]
    public void MoneyUpdateWritesOnlyChangedPagesAndPreservesEveryOtherByte(uint money)
    {
        var fake = new FakeCard();
        var store = new CharacterCardStore(fake.Card);
        store.Create(new Character("Ember") { Experience = 123, UnusedStatPoints = 7 });
        byte[] original = (byte[])fake.Memory.Clone();
        byte[] payload = CharacterSaveCodec.Encode(store.Load()!);
        int payloadStart = fake.Memory.AsSpan().IndexOf(payload);
        Assert.True(payloadStart >= 16);
        byte[] expected = (byte[])original.Clone();
        System.Buffers.Binary.BinaryPrimitives.WriteUInt32LittleEndian(expected.AsSpan(payloadStart + 9, 4), money);
        byte[] changedPages = Enumerable.Range(4, 126)
            .Where(page => !original.AsSpan(page * 4, 4).SequenceEqual(expected.AsSpan(page * 4, 4)))
            .Select(page => (byte)page).ToArray();
        fake.WrittenPages.Clear();

        Assert.Equal(changedPages.Length, store.UpdateMoney(money));

        Assert.Equal(changedPages, fake.WrittenPages);
        Assert.Equal(expected, fake.Memory);
        Assert.Equal(money, store.Load()!.Money);
        fake.WrittenPages.Clear();
        Assert.Equal(0, store.UpdateMoney(money));
        Assert.Empty(fake.WrittenPages);
    }

    [Fact]
    public void MoneyUpdateRejectsBlankAndMalformedCardsWithoutWriting()
    {
        var fake = new FakeCard();
        var store = new CharacterCardStore(fake.Card);
        Assert.Throws<InvalidOperationException>(() => store.UpdateMoney(42));
        fake.Memory[16] = 0xFE;
        Assert.Throws<InvalidDataException>(() => store.UpdateMoney(42));
        Assert.Empty(fake.WrittenPages);
    }

    [Fact]
    public void MoneyUpdateDetectsWritesThatDidNotReachCard()
    {
        var fake = new FakeCard();
        var store = new CharacterCardStore(fake.Card);
        store.Create(new Character("Ember"));
        fake.IgnoreWrites = true;
        Assert.Throws<IOException>(() => store.UpdateMoney(42));
    }

    private sealed class FakeCard
    {
        public byte[] Memory { get; } = new byte[540];
        public List<byte> WrittenPages { get; } = [];
        public bool IgnoreWrites { get; set; }
        public UltralightCard Card { get; }

        public FakeCard()
        {
            new byte[] { 0xE1, 0x10, 0x3E, 0 }.CopyTo(Memory, 12);
            Card = new UltralightCard(new PcscTransceiver(Exchange), 0);
        }

        private byte[] Exchange(byte[] command)
        {
            if (command[1] == 0) return [0, 4, 4, 2, 1, 0, 0x11, 3, 0x90, 0];
            if (command[1] == 0xB0) return [.. Memory.AsSpan(command[3] * 4, 16).ToArray(), 0x90, 0];
            Assert.Equal(0xD6, command[1]);
            WrittenPages.Add(command[3]);
            if (!IgnoreWrites) command.AsSpan(5, 4).CopyTo(Memory.AsSpan(command[3] * 4));
            return [0x90, 0];
        }
    }
}
