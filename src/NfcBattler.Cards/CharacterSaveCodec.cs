using System.Buffers.Binary;
using System.Text;
using NfcBattler.Core;

namespace NfcBattler.Cards;

// Offsets are relative to the 64-byte MIME payload, not physical card pages.
public static class CharacterSaveCodec
{
    public const string MimeType = "application/x-nfcbattler";
    public const byte CurrentVersion = 1;

    public static byte[] Encode(Character character)
    {
        if (string.IsNullOrWhiteSpace(character.Name) || character.Name.Length > 11 ||
            character.Name.Any(c => c < 32 || c > 126))
            throw new ArgumentException("Use a name of 1-11 printable ASCII characters.");
        if (character.UnlockedMovesBitmap.Length != 16)
            throw new ArgumentException("The unlock bitmap must contain 16 bytes.");

        byte[] data = new byte[64];
        data[0] = (byte)'N';
        data[1] = (byte)'B';
        data[2] = CurrentVersion;
        data[3] = character.ClassId;
        data[4] = checked((byte)character.Level);
        BinaryPrimitives.WriteUInt32LittleEndian(data.AsSpan(5), character.Experience);
        BinaryPrimitives.WriteUInt32LittleEndian(data.AsSpan(9), character.Money);
        data[13] = checked((byte)character.UnusedStatPoints);
        int[] stats = [character.MaxHealth, character.Attack, character.Defense,
            character.Speed, character.Magic, character.Luck];
        for (int i = 0; i < stats.Length; i++)
            BinaryPrimitives.WriteUInt16LittleEndian(data.AsSpan(14 + i * 2), checked((ushort)stats[i]));
        byte?[] moves = [character.Move1, character.Move2, character.Move3, character.Move4];
        for (int i = 0; i < moves.Length; i++)
        {
            if (moves[i] == 255) throw new ArgumentException("Move ID 255 is reserved for an empty slot.");
            data[26 + i] = moves[i] ?? 255;
        }
        Encoding.ASCII.GetBytes(character.Name).CopyTo(data, 30);
        character.UnlockedMovesBitmap.CopyTo(data, 42);
        return data;
    }

    public static Character Decode(ReadOnlySpan<byte> data)
    {
        if (data.Length != 64 || data[0] != 'N' || data[1] != 'B')
            throw new InvalidDataException("The character save is damaged or has an invalid NB marker. It will not be overwritten.");
        if (data[2] != CurrentVersion)
            throw new InvalidDataException($"Save format {data[2]} is unsupported. It will not be overwritten.");
        const int nameOffset = 30;
        const int bitmapOffset = 42;
        int nameLength = data.Slice(nameOffset, 12).IndexOf((byte)0);
        if (nameLength <= 0 || data.Slice(nameOffset, nameLength).ToArray().Any(b => b < 32 || b > 126))
            throw new InvalidDataException("The saved character name is invalid.");
        var character = new Character(Encoding.ASCII.GetString(data.Slice(nameOffset, nameLength)))
        {
            ClassId = data[3], Level = data[4],
            Experience = BinaryPrimitives.ReadUInt32LittleEndian(data[5..]),
            Money = BinaryPrimitives.ReadUInt32LittleEndian(data[9..]),
            UnusedStatPoints = data[13],
            MaxHealth = BinaryPrimitives.ReadUInt16LittleEndian(data[14..]),
            Attack = BinaryPrimitives.ReadUInt16LittleEndian(data[16..]),
            Defense = BinaryPrimitives.ReadUInt16LittleEndian(data[18..]),
            Speed = BinaryPrimitives.ReadUInt16LittleEndian(data[20..]),
            Magic = BinaryPrimitives.ReadUInt16LittleEndian(data[22..]),
            Luck = BinaryPrimitives.ReadUInt16LittleEndian(data[24..]),
            Move1 = data[26] == 255 ? null : data[26],
            Move2 = data[27] == 255 ? null : data[27],
            Move3 = data[28] == 255 ? null : data[28],
            Move4 = data[29] == 255 ? null : data[29],
            UnlockedMovesBitmap = data.Slice(bitmapOffset, 16).ToArray()
        };
        character.Health = character.MaxHealth;
        return character;
    }
}
