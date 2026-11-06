using System.Text.Json;
using System.Text.Json.Serialization;

namespace NfcBattler.Terminal;

public sealed record MoveDefinition(
    [property: JsonPropertyName("bitmapid")] byte BitmapId,
    [property: JsonPropertyName("moveid")] byte MoveId,
    [property: JsonPropertyName("name")] string Name,
    [property: JsonPropertyName("attack_bonus")] int AttackBonus);

public sealed record ClassDefinition(
    [property: JsonPropertyName("id")] byte Id,
    [property: JsonPropertyName("name")] string Name);

public sealed class GameCatalog
{
    public IReadOnlyDictionary<byte, MoveDefinition> Moves { get; }
    public IReadOnlyDictionary<byte, ClassDefinition> Classes { get; }

    public GameCatalog(string directory)
    {
        var moves = JsonSerializer.Deserialize<MoveDefinition[]>(File.ReadAllText(Path.Combine(directory, "moves.json")))
            ?? throw new InvalidDataException("moves.json is empty.");
        var classes = JsonSerializer.Deserialize<ClassDefinition[]>(File.ReadAllText(Path.Combine(directory, "classes.json")))
            ?? throw new InvalidDataException("classes.json is empty.");
        if (moves.Any(m => m is null || m.BitmapId >= 128 || m.MoveId == 255 || string.IsNullOrWhiteSpace(m.Name)) ||
            moves.Select(m => m.MoveId).Distinct().Count() != moves.Length ||
            moves.Select(m => m.BitmapId).Distinct().Count() != moves.Length)
            throw new InvalidDataException("Move IDs and bitmap IDs must be unique; bitmap IDs must be 0-127 and move IDs 0-254.");
        if (classes.Any(c => c is null || string.IsNullOrWhiteSpace(c.Name)) ||
            classes.Select(c => c.Id).Distinct().Count() != classes.Length || !classes.Any(c => c.Id == 0))
            throw new InvalidDataException("Class IDs must be unique and include class 0.");
        Moves = moves.ToDictionary(m => m.MoveId);
        Classes = classes.ToDictionary(c => c.Id);
    }

    public string ClassName(byte id) => Classes.TryGetValue(id, out var definition) ? definition.Name : "Unknown class";

    public string MoveName(byte? id) => id is null ? "Empty" :
        Moves.TryGetValue(id.Value, out var definition) ? $"{definition.Name} (ID {id}, attack bonus {definition.AttackBonus})" : $"Unknown move (ID {id})";
}
