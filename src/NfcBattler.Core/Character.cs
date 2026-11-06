namespace NfcBattler.Core;

public class Character
{
    // Properties hold the character's current values.
    public string Name { get; set; }
    public int Level { get; set; } = 0;
    public int Experience { get; set; } = 0;
    public int MaxHealth { get; set; } = 100;
    public int Health { get; set; }
    public int Attack { get; set; } = 10;
    public int Defense { get; set; } = 5;
    public int Speed { get; set; } = 1;
    public int Magic { get; set; } = 1;
    public int Luck { get; set; } = 1;
    public int Money { get; set; } = 0;
    public int UnusedStatPoints { get; set; } = 0;
    public byte Move1 { get; set; } = 0;
    public byte Move2 { get; set; } = 0;
    public byte Move3 { get; set; } = 0;
    public byte Move4 { get; set; } = 0;
    public byte[] UnlockedMovesBitmap { get; set; } = new byte[16];



    public Character(string name)
    {
        Name = name;
        Health = MaxHealth;
    }
}


public class Move
{
    public byte Id { get; set; }
    public string Name { get; set; } 
    public int Power { get; set; }

    public Move(byte id, string name, int power)
    {
        Id = id;
        Name = name;
        Power = power;
    }
}