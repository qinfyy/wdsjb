using Google.Protobuf;
using PlayerSaveProto;
using Microsoft.Data.Sqlite;
using Microsoft.EntityFrameworkCore;
using Serilog;
using Sv.Configuration;
using Sv.Game;
using Sv.Utility;

namespace Sv.Database;

public sealed partial class GameDatabase
{
    private static GameDatabase? _instance;
    public static GameDatabase Instance => _instance ?? throw new InvalidOperationException("数据库尚未初始化");
    private readonly DbContextOptions<GameDbContext> _dbContextOptions;
    private readonly Lock _writeLock = new();
    private readonly Dictionary<(int ChannelId, string OpenId), Player> _players = [];
    private GameDatabase(DbContextOptions<GameDbContext> options) => _dbContextOptions = options;
    private GameDbContext CreateDbContext() => new(_dbContextOptions);

    public static void Initialize(DatabaseOptions options)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(options.Path)!);
        SqliteConnectionStringBuilder connection = new() { DataSource = options.Path, ForeignKeys = true, DefaultTimeout = 5 };
        DbContextOptionsBuilder<GameDbContext> builder = new();
        builder.UseSqlite(connection.ConnectionString);
        GameDatabase database = new(builder.Options);
        using GameDbContext db = database.CreateDbContext();
        db.Database.EnsureCreated();
        db.Database.ExecuteSqlRaw("PRAGMA journal_mode=WAL;");
        _instance = database;
        Log.Information("数据库已初始化: {Path}", options.Path);
    }

    public Player GetOrCreateByAccount(int channelId, string openId)
    {
        lock (_writeLock)
        {
            if (_players.TryGetValue((channelId, openId), out Player? cached)) return cached;
            using GameDbContext db = CreateDbContext();
            PlayerEntity? entity = db.Players.SingleOrDefault(value => value.ChannelId == channelId && value.OpenId == openId);
            bool isNew = entity is null;
            if (entity is null)
            {
                entity = new PlayerEntity
                {
                    ChannelId = channelId, OpenId = openId,
                    CreatedAt = Time.Now, UpdatedAt = Time.Now,
                };
            }
            PlayerSaveData data = isNew ? InitialPlayerTemplate.CreateSaveData() : PlayerSaveData.Parser.ParseFrom(entity.Data);
            using var transaction = isNew ? db.Database.BeginTransaction() : null;
            if (isNew) { entity.Data = data.ToByteArray(); db.Players.Add(entity); db.SaveChanges(); }
            if (entity.Uid is <= 0 or > uint.MaxValue) throw new InvalidOperationException("玩家 UID 超出协议范围");
            Player player = new(entity.Uid, entity.ChannelId, entity.OpenId, data, isNew);
            if (isNew) { entity.Data = data.ToByteArray(); db.SaveChanges(); transaction!.Commit(); }
            _players.Add((channelId, openId), player);
            return player;
        }
    }

    public Player[] GetLoadedPlayers()
    {
        lock (_writeLock) return _players.Values.ToArray();
    }

    public void Save(Player player)
    {
        lock (player.SyncRoot)
        lock (_writeLock)
        {
            using GameDbContext db = CreateDbContext();
            PlayerEntity entity = db.Players.Single(value => value.Uid == player.Uid);
            entity.Data = player.SaveData.ToByteArray();
            entity.UpdatedAt = Time.Now;
            db.SaveChanges();
        }
    }
}
