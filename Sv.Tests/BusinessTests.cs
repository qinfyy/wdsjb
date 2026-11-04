using Microsoft.Data.Sqlite;
using Sv.Configuration;
using Sv.Database;
using Sv.Game;
using Sv.Resources;
using Sv.Resources.Tables;
using Xunit;

namespace Sv.Tests;

public sealed class ServerFixture : IDisposable
{
    private readonly string _directory = Path.Combine(Path.GetTempPath(), "server-tests", Guid.NewGuid().ToString("N"));
    public string DatabasePath => Path.Combine(_directory, "SaveData.db");
    public ServerFixture()
    {
        string root = Path.GetFullPath("../../../../StaticResParser/output", AppContext.BaseDirectory);
        ResourcesLoader.Load(new GameDataOptions { TableRoot = root });
        Directory.CreateDirectory(_directory); GameDatabase.Initialize(new DatabaseOptions { Path = DatabasePath });
    }
    public void Dispose()
    {
        SqliteConnection.ClearAllPools(); Directory.Delete(_directory, recursive: true);
    }
}

[Collection("Server")]
public sealed class BusinessTests(ServerFixture fixture)
{
    private static Player CreatePlayer() => GameDatabase.Instance.GetOrCreateByAccount(1, Guid.NewGuid().ToString("N"));
    [Fact]
    public void RealTablesCompleteThreeStageLoading()
    {
        GameTableCatalog catalog = GameTableCatalog.Instance;
        Assert.True(catalog.IsLoaded); Assert.Equal(10, catalog.LoadedTableCount);
        PlayerLevelData level = Assert.IsType<PlayerLevelData>(catalog.GetDataById<PlayerLevelData>(1));
        Assert.Equal(81u, level.Stamina); Assert.Equal(1500, level.NextLevelExp); Assert.NotNull(level.NextLevel);
        CardData card = catalog.GetAllData<CardData>().First(); Assert.NotNull(card.Role); Assert.Contains(card, card.Role.Cards);
        LevelData first = Assert.IsType<LevelData>(catalog.GetDataById<LevelData>(1)); Assert.NotNull(first.Chapter); Assert.NotNull(first.FirstReward);
        LevelData second = Assert.IsType<LevelData>(catalog.GetDataById<LevelData>(2)); Assert.Contains(first, second.Parents); Assert.Contains(second, first.Children);
        Assert.Equal(new uint[] { 5, 6 }, catalog.GetDataById<LevelData>(7)!.StoryIds);
    }
    [Fact]
    public void SdkTokenChainValidatesOnlyIssuedAccountSession()
    {
        GameDatabase database = GameDatabase.Instance;
        AccountTokenResult login = database.LoginAccountByPassword(Guid.NewGuid().ToString("N"), "demo-password");
        AccountVerifyResult verify = database.VerifyAccountSession(login.Account.Aid, login.TokenType, login.Token, refresh: true);
        Assert.Null(verify.NewToken);
        AccountTokenResult game = database.ExchangeAccountToken(login.Account.Aid, login.TokenType, login.Token, 4);
        AccountComboResult combo = database.GrantAccountComboToken(login.Account.Aid, game.Token, 1);
        Assert.True(database.ValidateAccountComboToken(1, login.Account.Aid, combo.ComboToken));
        Assert.False(database.ValidateAccountComboToken(2, login.Account.Aid, combo.ComboToken));
        Assert.False(database.ValidateAccountComboToken(1, "invalid-account", combo.ComboToken));
        Assert.False(database.ValidateAccountComboToken(1, login.Account.Aid, "captured-or-forged-token"));
    }
    [Fact]
    public void PlayerPersistsWithoutNetworkPacketsOrGameNamePrefix()
    {
        GameDatabase database = GameDatabase.Instance;
        Player player = CreatePlayer();
        lock (player.SyncRoot) { player.Profile.Rename("Saved", sync: false); player.Save(); }
        Assert.Same(player, database.GetOrCreateByAccount(player.ChannelId, player.OpenId));
        GameDatabase.Initialize(new DatabaseOptions { Path = fixture.DatabasePath });
        Player loaded = GameDatabase.Instance.GetOrCreateByAccount(player.ChannelId, player.OpenId);
        Assert.Equal("Saved", loaded.Profile.Nickname); Assert.Equal(player.Uid, loaded.Uid);
        Assert.Equal(player.Inventory.Cards.Count(), loaded.Inventory.Cards.Count());
        using SqliteConnection connection = new($"Data Source={fixture.DatabasePath}"); connection.Open();
        using SqliteCommand command = connection.CreateCommand(); command.CommandText = "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'Players'";
        Assert.Equal("Players", command.ExecuteScalar());
        Assert.DoesNotContain(typeof(Pbplayer.GetMainDataReq).Assembly.GetTypes(), type => type.Namespace == "Wd");
    }
    [Fact]
    public void FailedAssetAndDeckOperationsDoNotChangeState()
    {
        Player player = CreatePlayer();
        lock (player.SyncRoot)
        {
            Assert.Throws<PlayerActionException>(() => player.Wallet.Spend(RewardKind.Hcoin, 0, 10, sync: false)); Assert.Equal(0, player.Wallet.Hcoin);
            uint[] before = player.Inventory.GetDeck(1).MainCards.ToArray();
            Assert.Throws<PlayerActionException>(() => player.Inventory.ChangeDeck(1, "Invalid", [uint.MaxValue], [], sync: false));
            Assert.Equal(before, player.Inventory.GetDeck(1).MainCards);
            Assert.Throws<PlayerActionException>(() => player.Inventory.GrantRewards(new RewardItemData[]
            {
                new() { Type = RewardKind.Hcoin, ItemId = 1, Count = 10 }, new() { Type = RewardKind.Material, ItemId = uint.MaxValue, Count = 1 },
            }, sync: false));
            Assert.Equal(0, player.Wallet.Hcoin);
        }
    }
    [Fact]
    public void StoryLevelRewardsAreCalculatedFromTablesAndFirstPassIsIdempotent()
    {
        Player player = CreatePlayer();
        lock (player.SyncRoot)
        {
            Assert.Throws<PlayerActionException>(() => player.Level.Complete(1, sync: false));
            player.Level.Begin(1);
            Assert.Throws<PlayerActionException>(() => player.Level.Complete(1, sync: false)); Assert.Equal(0, player.Wallet.Hcoin);
            player.Story.Complete(1); Assert.True(player.Level.Complete(1, sync: false)); player.Save();
            Assert.Equal(40, player.Wallet.Hcoin); Assert.Equal(100u, player.Profile.Exp); Assert.Equal(71u, player.Profile.Stamina);
            Assert.Throws<PlayerActionException>(() => player.Level.Complete(1, sync: false)); Assert.Equal(40, player.Wallet.Hcoin);
            player.Level.Begin(1); Assert.False(player.Level.Complete(1, sync: false)); player.Save();
            Assert.Equal(40, player.Wallet.Hcoin); Assert.Equal(2u, player.Level.PassCount(1)); Assert.True(player.Level.IsOpen(2));
        }
    }
}
