using System.Globalization;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Storage.ValueConversion;
using Sv.Utility;

namespace Sv.Database;

public sealed class GameDbContext(DbContextOptions<GameDbContext> options) : DbContext(options)
{
    /// <summary>SQLite 里 DateTimeOffset 的存法（与 EF 默认格式一致），一律带配置时区偏移。</summary>
    private const string TimeFormat = "yyyy-MM-dd HH:mm:ss.fffffffzzz";

    /// <summary>写库前换算到配置时区，读库后再换算一次：库里偏移稳定，换时区配置也能正确还原。</summary>
    private static readonly ValueConverter<DateTimeOffset, string> TimeZoneConverter = new(
        value => Time.InTimeZone(value).ToString(TimeFormat, CultureInfo.InvariantCulture),
        text => Time.InTimeZone(DateTimeOffset.Parse(text, CultureInfo.InvariantCulture)));

    private static readonly ValueConverter<DateTimeOffset?, string?> NullableTimeZoneConverter = new(
        value => value.HasValue ? Time.InTimeZone(value.Value).ToString(TimeFormat, CultureInfo.InvariantCulture) : null,
        text => string.IsNullOrEmpty(text) ? null : Time.InTimeZone(DateTimeOffset.Parse(text, CultureInfo.InvariantCulture)));

    public DbSet<PlayerEntity> Players => Set<PlayerEntity>();
    public DbSet<AccountEntity> Accounts => Set<AccountEntity>();

    protected override void OnModelCreating(ModelBuilder modelBuilder)
    {
        modelBuilder.Entity<PlayerEntity>(entity =>
        {
            entity.ToTable("Players");
            entity.HasKey(value => value.Uid);
            entity.Property(value => value.Uid).ValueGeneratedOnAdd();
            entity.HasIndex(value => value.Uuid).IsUnique();
            entity.HasIndex(nameof(PlayerEntity.ChannelId), nameof(PlayerEntity.OpenId)).IsUnique();
            entity.Property(value => value.Uuid).HasMaxLength(50);
            entity.Property(value => value.OpenId).HasMaxLength(75);
            entity.Property(value => value.CreatedAt).HasConversion(TimeZoneConverter);
            entity.Property(value => value.UpdatedAt).HasConversion(TimeZoneConverter);
        });

        modelBuilder.Entity<AccountEntity>(entity =>
        {
            entity.ToTable("Accounts");
            entity.HasKey(value => value.Aid);
            entity.Property(value => value.Aid).ValueGeneratedOnAdd();
            entity.HasIndex(value => value.Username).IsUnique();
            entity.HasIndex(value => value.Mobile).IsUnique();
            entity.Property(value => value.Username).HasMaxLength(512);
            entity.Property(value => value.Mobile).HasMaxLength(512);
            entity.Property(value => value.AreaCode).HasMaxLength(512);
            entity.Property(value => value.Password).HasMaxLength(1024);
            entity.Property(value => value.SessionToken).HasMaxLength(512);
            entity.Property(value => value.GameToken).HasMaxLength(512);
            entity.Property(value => value.ComboToken).HasMaxLength(512);
            entity.Property(value => value.SessionTokenExpiresAt).HasConversion(NullableTimeZoneConverter);
            entity.Property(value => value.GameTokenExpiresAt).HasConversion(NullableTimeZoneConverter);
            entity.Property(value => value.ComboTokenExpiresAt).HasConversion(NullableTimeZoneConverter);
            entity.Property(value => value.CreatedAt).HasConversion(TimeZoneConverter);
            entity.Property(value => value.UpdatedAt).HasConversion(TimeZoneConverter);
            entity.Property(value => value.LastLoginAt).HasConversion(TimeZoneConverter);
        });
    }
}
