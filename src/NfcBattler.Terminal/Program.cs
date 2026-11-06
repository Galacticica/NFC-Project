using System.Text.Json;
using NfcBattler.Cards;
using NfcBattler.Core;
using NfcBattler.Terminal;
using PCSC.Exceptions;

Console.WriteLine("Welcome to NFC Card Battler!");
GameCatalog catalog;
try
{
    catalog = new GameCatalog(Path.Combine(AppContext.BaseDirectory, "data"));
}
catch (Exception ex) when (ex is IOException or JsonException)
{
    Console.WriteLine($"Could not load game data: {ex.Message}");
    return;
}

while (true)
{
    Console.WriteLine("\n1. Read character card\n2. Create character on a blank card\n3. Clear an NFC card\n0. Exit");
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
            if (!int.TryParse(Console.ReadLine(), out int number) || number < 1 || number > readers.Length) continue;
            selected = number - 1;
        }
        Console.WriteLine($"Reader: {readers[selected]}");
        Console.Write("Place an NTAG215 card on the reader and press Enter (or type cancel). Keep it there until finished: ");
        string? ready = Console.ReadLine();
        if (ready is null || ready.Trim().Equals("cancel", StringComparison.OrdinalIgnoreCase)) continue;
        using var session = new NfcCardSession(readers[selected]);
        Console.WriteLine($"UID: {session.Uid} | Type: NTAG215");
        if (choice == "3")
        {
            Console.Write("Erase all user data? Type CLEAR to confirm (character saves are protected): ");
            if (Console.ReadLine() != "CLEAR") { Console.WriteLine("Clear cancelled."); continue; }
            session.Clear();
            Console.WriteLine("Cleared and verified successfully.");
            continue;
        }

        Character? character = session.LoadCharacter();
        if (character is null)
        {
            Console.Write("This card is blank. Create a character? (y/N): ");
            if (!string.Equals(Console.ReadLine()?.Trim(), "y", StringComparison.OrdinalIgnoreCase)) continue;
            string name;
            while (true)
            {
                Console.Write("Character name: 1-11 ASCII characters (Enter to cancel): ");
                string? input = Console.ReadLine()?.Trim();
                if (string.IsNullOrEmpty(input)) { name = ""; break; }
                if (input.Length <= 11 && input.All(c => c >= 32 && c <= 126)) { name = input; break; }
                Console.WriteLine("Use 1-11 printable ASCII characters.");
            }
            if (name.Length == 0) continue;
            foreach (var entry in catalog.Classes.Values.Where(c => c.Name != "TBD"))
                Console.WriteLine($"{entry.Id}: {entry.Name}");
            Console.Write("Class ID (Enter for 0 / No Class): ");
            string? classInput = Console.ReadLine();
            if (classInput is null) continue;
            byte classId = 0;
            if (!string.IsNullOrWhiteSpace(classInput) &&
                (!byte.TryParse(classInput, out classId) || !catalog.Classes.ContainsKey(classId)))
            {
                Console.WriteLine("Unknown class ID. Creation cancelled.");
                continue;
            }
            character = new Character(name) { ClassId = classId };
            PrintCharacter(character, catalog);
            Console.Write("Write this character to the card? Type CREATE to confirm: ");
            if (Console.ReadLine() != "CREATE") { Console.WriteLine("Creation cancelled."); continue; }
            session.CreateCharacter(character);
            character = session.LoadCharacter() ?? throw new IOException("The saved character could not be loaded.");
            Console.WriteLine("Character saved and verified.");
        }
        PrintCharacter(character, catalog);
    }
    catch (Exception ex) when (ex is PCSCException or IOException or ArgumentException or
        NotSupportedException or InvalidOperationException or OverflowException)
    {
        Console.WriteLine($"NFC operation failed: {ex.Message}");
        Console.WriteLine("If a write was interrupted, read the card again to check its contents.");
    }
}

static void PrintCharacter(Character character, GameCatalog catalog)
{
    Console.WriteLine($"\n--- {character.Name} ---");
    Console.WriteLine($"Class: {catalog.ClassName(character.ClassId)} (ID {character.ClassId})");
    Console.WriteLine($"Level: {character.Level} | XP: {character.Experience} | Money: {character.Money}");
    Console.WriteLine($"HP: {character.Health}/{character.MaxHealth} | Unused stat points: {character.UnusedStatPoints}");
    Console.WriteLine($"Base stats: ATK {character.Attack} | DEF {character.Defense} | SPD {character.Speed} | MAG {character.Magic} | LCK {character.Luck}");
    byte?[] equipped = [character.Move1, character.Move2, character.Move3, character.Move4];
    for (int i = 0; i < equipped.Length; i++) Console.WriteLine($"Move {i + 1}: {catalog.MoveName(equipped[i])}");
    Console.WriteLine("Unlocked moves:");
    for (int bit = 0; bit < 128; bit++)
    {
        if ((character.UnlockedMovesBitmap[bit / 8] & (1 << (bit % 8))) == 0) continue;
        var move = catalog.Moves.Values.FirstOrDefault(m => m.BitmapId == bit);
        Console.WriteLine(move is null ? $"  Unknown bitmap ID {bit}" : $"  {catalog.MoveName(move.MoveId)} [bitmap {bit}]");
    }
}
