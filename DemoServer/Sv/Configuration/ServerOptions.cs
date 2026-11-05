namespace Sv.Configuration;

public sealed class ServerOptions
{
    public const string SectionName = "Server";
    public int HttpPort { get; init; } = 21000;
    public int GamePort { get; init; } = 24088;
    public string AdvertiseHost { get; init; } = "127.0.0.1";
    public int AdvertisePort { get; init; } = 24088;
    public string AdvertiseIpv6 { get; init; } = string.Empty;
    public string Region { get; init; } = "cn_prod_gf01";
    public string RegionTitle { get; init; } = "Demo";
    public string ClientVersion { get; init; } = "6.1.0.2";
    public uint ResourceId { get; init; } = 8127;
    public uint IosResourceId { get; init; } = 8126;
    public string ResourceVersion { get; init; } = "2026102715";
    public string ResourceSuffix { get; init; } = "d972d6cae1";
    public uint DesignDataId { get; init; } = 8500;
    public string DesignDataVersion { get; init; } = "793850";
    public string DesignDataSuffix { get; init; } = "a81d28b211";
    public string TimeZone { get; init; } = "China Standard Time";
    public int MaxFrameBytes { get; init; } = 16 * 1024 * 1024;
    public int IdleTimeoutSeconds { get; init; } = 120;
    public int SaveIntervalSeconds { get; init; } = 60;
    public Uri AssetOrigin { get; init; } = new("https://download.themisweeps.com");
    public bool ProxyAssets { get; init; } = true;
    public string PublicHttpUrl => $"http://{(AdvertiseHost.Contains(':') ? $"[{AdvertiseHost}]" : AdvertiseHost)}:{HttpPort}";

    public static ServerOptions FromConfiguration(IConfiguration configuration)
    {
        ServerOptions options = configuration.GetRequiredSection(SectionName).Get<ServerOptions>() ?? new();
        if (new[] { options.HttpPort, options.GamePort, options.AdvertisePort }.Any(port => port is < 1 or > 65535)
            || options.HttpPort == options.GamePort)
            throw new InvalidOperationException("HTTP/TCP 端口无效或冲突");
        if (string.IsNullOrWhiteSpace(options.AdvertiseHost) || string.IsNullOrWhiteSpace(options.Region))
            throw new InvalidOperationException("AdvertiseHost 和 Region 不能为空");
        if (options.MaxFrameBytes < 12 || options.IdleTimeoutSeconds < 1 || options.SaveIntervalSeconds < 1)
            throw new InvalidOperationException("帧长度与超时配置无效");
        if (!options.AssetOrigin.IsAbsoluteUri || options.AssetOrigin.Scheme is not ("http" or "https"))
            throw new InvalidOperationException("AssetOrigin 必须为 HTTP/HTTPS 地址");
        return options;
    }
}
