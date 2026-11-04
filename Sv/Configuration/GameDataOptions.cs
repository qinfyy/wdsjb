namespace Sv.Configuration;

public sealed class GameDataOptions
{
    public string TableRoot { get; init; } = "D:/Il2Cpp/wd/StaticResParser/output";
    public static GameDataOptions FromConfiguration(IConfiguration configuration, string root)
    {
        GameDataOptions options = configuration.GetRequiredSection("GameData").Get<GameDataOptions>() ?? new();
        string path = Path.GetFullPath(options.TableRoot, root);
        if (!Directory.Exists(path)) throw new InvalidDataException($"策划资源目录不存在: {path}");
        return new GameDataOptions { TableRoot = path };
    }
}
