using System.Text.Json;
using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Hosting.Server;
using Microsoft.AspNetCore.Hosting.Server.Features;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Sv.Configuration;
using Sv.Http;
using Xunit;

namespace Sv.Tests;

[Collection("Server")]
public sealed class DispatchTests
{
    [Theory]
    [InlineData(true, "GET")]
    [InlineData(true, "POST")]
    [InlineData(false, "GET")]
    [InlineData(false, "POST")]
    public async Task QueryRegionPreservesSdkPlatformKeysAndCapturedResourceVersions(bool proxyAssets, string method)
    {
        string root = Path.GetFullPath("../../../../Sv", AppContext.BaseDirectory);
        IConfiguration previous = Config.Root ?? CreateConfiguration(root, true);
        WebApplicationBuilder builder = WebApplication.CreateSlimBuilder();
        builder.WebHost.UseUrls("http://127.0.0.1:0");
        await using WebApplication app = builder.Build();
        try
        {
            Config.Initialize(CreateConfiguration(root, proxyAssets), root);
            app.MapDispatchEndpoints();
            await app.StartAsync();
            var addresses = app.Services.GetRequiredService<IServer>().Features.Get<IServerAddressesFeature>()!;
            using HttpClient client = new() { BaseAddress = new Uri(Assert.Single(addresses.Addresses)) };
            using HttpRequestMessage request = new(new HttpMethod(method), "/query_region?version=6.1.0.2&lang=zh-cn");
            using HttpResponseMessage response = await client.SendAsync(request);
            response.EnsureSuccessStatusCode();
            using JsonDocument actual = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
            using FileStream capture = File.OpenRead(Path.Combine(root, "../Reverse/HTTP自动登录.har"));
            using JsonDocument har = await JsonDocument.ParseAsync(capture);
            JsonElement entry = Assert.Single(har.RootElement.GetProperty("log").GetProperty("entries").EnumerateArray(),
                item => new Uri(item.GetProperty("request").GetProperty("url").GetString()!).AbsolutePath == "/query_region");
            using JsonDocument expected = JsonDocument.Parse(entry.GetProperty("response").GetProperty("content").GetProperty("text").GetString()!);
            JsonElement region = actual.RootElement.GetProperty("data").GetProperty("region_info")[0];
            JsonElement reference = expected.RootElement.GetProperty("data").GetProperty("region_info")[0];
            JsonElement platforms = region.GetProperty("region_res_cfg").GetProperty("plat_res");
            Assert.False(platforms.TryGetProperty("android", out _));
            foreach (string platform in new[] { "Android", "iOS" })
            {
                JsonElement resources = platforms.GetProperty(platform).GetProperty("res_arr")[0];
                JsonElement captured = reference.GetProperty("region_res_cfg").GetProperty("plat_res").GetProperty(platform).GetProperty("res_arr")[0];
                foreach (string field in new[] { "res_id", "res_version", "version_suffix", "plat" })
                    Assert.True(JsonElement.DeepEquals(captured.GetProperty(field), resources.GetProperty(field)), $"{platform}.{field} 与 HAR 不一致");
                string suffix = $"/output_{resources.GetProperty("res_version").GetString()}_{resources.GetProperty("version_suffix").GetString()}/client/{platform}";
                string assets = proxyAssets ? Config.Server.PublicHttpUrl : Config.Server.AssetOrigin.GetLeftPart(UriPartial.Authority);
                string resourceBase = region.GetProperty("resource_url").GetString()!;
                Assert.Equal($"{assets}/client_game_res/{Config.Server.Region}{suffix}", resourceBase + suffix);
                Assert.Equal(resourceBase, region.GetProperty("resource_url_bak").GetString());
            }
            JsonElement design = region.GetProperty("region_design_cfg").GetProperty("design_data")[0];
            JsonElement capturedDesign = reference.GetProperty("region_design_cfg").GetProperty("design_data")[0];
            foreach (string field in new[] { "cfg_id", "cfg_version", "version_suffix" })
                Assert.True(JsonElement.DeepEquals(capturedDesign.GetProperty(field), design.GetProperty(field)), $"design_data.{field} 与 HAR 不一致");
            string dataBase = region.GetProperty("data_url").GetString()!;
            Assert.Equal(dataBase, region.GetProperty("data_url_bak").GetString());
            Assert.EndsWith($"/client_design_data/{Config.Server.Region}", dataBase);
            Assert.Equal(Config.Server.PublicHttpUrl, region.GetProperty("dispatch_url").GetString());
            Assert.Equal(Config.Server.PublicHttpUrl, region.GetProperty("account_url").GetString());
            Assert.Equal(200, actual.RootElement.GetProperty("code").GetInt32());
        }
        finally { await app.StopAsync(); Config.Initialize(previous, root); }
    }

    private static IConfiguration CreateConfiguration(string root, bool proxyAssets) => new ConfigurationBuilder()
        .AddInMemoryCollection(new Dictionary<string, string?>
        {
            ["Server:HttpPort"] = "21000", ["Server:ProxyAssets"] = proxyAssets.ToString(), ["Database:Path"] = "save/SaveData.db",
            ["GameData:TableRoot"] = Path.GetFullPath("../StaticResParser/output", root),
        }).Build();
}
