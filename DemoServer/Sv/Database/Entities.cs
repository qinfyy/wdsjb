namespace Sv.Database;

public sealed class PlayerEntity
{
    public long Uid { get; set; }
    public int ChannelId { get; set; }
    public string OpenId { get; set; } = string.Empty;
    public DateTimeOffset CreatedAt { get; set; }
    public DateTimeOffset UpdatedAt { get; set; }
    public byte[] Data { get; set; } = [];
}

public sealed class AccountEntity
{
    public long Aid { get; set; }
    public string? Username { get; set; }
    public string? Mobile { get; set; }
    public string AreaCode { get; set; } = string.Empty;
    public string? Password { get; set; }
    public string? SessionToken { get; set; }
    public DateTimeOffset? SessionTokenExpiresAt { get; set; }
    public string? GameToken { get; set; }
    public DateTimeOffset? GameTokenExpiresAt { get; set; }
    public string? ComboToken { get; set; }
    public DateTimeOffset? ComboTokenExpiresAt { get; set; }
    public int ComboChannelId { get; set; }
    public DateTimeOffset CreatedAt { get; set; }
    public DateTimeOffset UpdatedAt { get; set; }
    public DateTimeOffset LastLoginAt { get; set; }
}
