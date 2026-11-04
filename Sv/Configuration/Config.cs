namespace Sv.Configuration;

public static class Config
{
    public static IConfiguration Root { get; private set; } = null!;
    public static ServerOptions Server { get; private set; } = new();
    public static DatabaseOptions Database { get; private set; } = new();
    public static AccountOptions Account { get; private set; } = new();
    public static GameDataOptions GameData { get; private set; } = new();

    public static void Initialize(IConfiguration configuration, string contentRootPath)
    {
        Root = configuration;
        Server = ServerOptions.FromConfiguration(configuration);
        Database = DatabaseOptions.FromConfiguration(configuration, contentRootPath);
        Account = AccountOptions.FromConfiguration(configuration);
        GameData = GameDataOptions.FromConfiguration(configuration, contentRootPath);
    }
}
