using Iot.Device.Card.Ultralight;
using NfcBattler.Cards;
using Xunit;

namespace NfcBattler.Tests;

public class ClearCardTests
{
    [Fact]
    public void ClearErasesAllUserMemoryAndPreservesOtherPages()
    {
        var fake = new FakeCard();
        byte[] original = (byte[])fake.Memory.Clone();

        Ntag215Tools.Clear(fake.Card);

        Assert.Equal(new byte[] { 3, 0, 0xFE, 0 }, fake.Memory[16..20]);
        Assert.All(fake.Memory[20..520], value => Assert.Equal(0, value));
        Assert.Equal(original[..16], fake.Memory[..16]);
        Assert.Equal(original[520..], fake.Memory[520..]);
        Assert.Equal(Enumerable.Range(4, 126).Select(i => (byte)i), fake.WrittenPages);
    }

    [Fact]
    public void ClearDetectsResidualDataOnLastUserPage()
    {
        var fake = new FakeCard { IgnoreLastWrite = true };
        Assert.Throws<IOException>(() => Ntag215Tools.Clear(fake.Card));
    }

    [Fact]
    public void ClearRejectsReadOnlyCardWithoutWriting()
    {
        var fake = new FakeCard();
        fake.Memory[15] = 0x0F;
        Assert.Throws<IOException>(() => Ntag215Tools.Clear(fake.Card));
        Assert.Empty(fake.WrittenPages);
    }

    [Fact]
    public void ClearErasesGameSaveAndAllowsNewCharacter()
    {
        var fake = new FakeCard();
        // Start with a blank user area, then create a real save.
        Array.Clear(fake.Memory, 16, 504);
        var store = new CharacterCardStore(fake.Card);
        store.Create(new NfcBattler.Core.Character("Ember"));
        fake.WrittenPages.Clear();

        Ntag215Tools.Clear(fake.Card);

        Assert.Equal(Enumerable.Range(4, 126).Select(i => (byte)i), fake.WrittenPages);
        Assert.Equal(new byte[] { 3, 0, 0xFE, 0 }, fake.Memory[16..20]);
        Assert.All(fake.Memory[20..520], value => Assert.Equal(0, value));
        Assert.Null(store.Load());
        store.Create(new NfcBattler.Core.Character("New"));
        Assert.Equal("New", store.Load()!.Name);
    }

    private sealed class FakeCard
    {
        public byte[] Memory { get; } = Enumerable.Repeat((byte)0xA5, 540).ToArray();
        public List<byte> WrittenPages { get; } = [];
        public bool IgnoreLastWrite { get; init; }
        public UltralightCard Card { get; }

        public FakeCard()
        {
            new byte[] { 0xE1, 0x10, 0x3E, 0 }.CopyTo(Memory, 12);
            new byte[] { 3, 0, 0xFE, 0 }.CopyTo(Memory, 16);
            Card = new UltralightCard(new PcscTransceiver(Exchange), 0);
        }

        private byte[] Exchange(byte[] command)
        {
            if (command[1] == 0) return [0, 4, 4, 2, 1, 0, 0x11, 3, 0x90, 0];
            if (command[1] == 0xB0)
                return [.. Memory.AsSpan(command[3] * 4, 16).ToArray(), 0x90, 0];
            Assert.Equal(0xD6, command[1]);
            WrittenPages.Add(command[3]);
            if (!(IgnoreLastWrite && command[3] == 129))
                command.AsSpan(5, 4).CopyTo(Memory.AsSpan(command[3] * 4));
            return [0x90, 0];
        }
    }
}
