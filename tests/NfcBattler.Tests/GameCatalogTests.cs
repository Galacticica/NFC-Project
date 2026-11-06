using NfcBattler.Terminal;
using Xunit;

namespace NfcBattler.Tests;

public class GameCatalogTests
{
    [Fact]
    public void LookupUsesMoveIdAndPreservesSeparateBitmapId()
    {
        WithCatalog("""
            [{"bitmapid":127,"moveid":254,"name":"Meteor","attack_bonus":25}]
            """, catalog =>
        {
            Assert.Equal("No Class", catalog.ClassName(0));
            Assert.Equal("Meteor (ID 254, attack bonus 25)", catalog.MoveName(254));
            Assert.Equal(127, catalog.Moves[254].BitmapId);
            Assert.Equal("Empty", catalog.MoveName(null));
            Assert.Equal("Unknown move (ID 12)", catalog.MoveName(12));
            Assert.Equal("Unknown class", catalog.ClassName(99));
        });
    }

    [Fact]
    public void CatalogRejectsDuplicateMoveIds()
    {
        Assert.Throws<InvalidDataException>(() => WithCatalog("""
            [{"bitmapid":0,"moveid":2,"name":"A","attack_bonus":0},
             {"bitmapid":1,"moveid":2,"name":"B","attack_bonus":0}]
            """, _ => { }));
    }

    private static void WithCatalog(string moves, Action<GameCatalog> action)
    {
        string directory = Path.Combine(Path.GetTempPath(), $"nfcbattler-catalog-{Guid.NewGuid():N}");
        Directory.CreateDirectory(directory);
        string moveFile = Path.Combine(directory, "moves.json");
        string classFile = Path.Combine(directory, "classes.json");
        try
        {
            File.WriteAllText(moveFile, moves);
            File.WriteAllText(classFile, """[{"id":0,"name":"No Class"}]""");
            action(new GameCatalog(directory));
        }
        finally
        {
            File.Delete(moveFile);
            File.Delete(classFile);
            Directory.Delete(directory);
        }
    }
}
