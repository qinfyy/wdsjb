using System.Text.Json;
using Sv.Configuration;
using Sv.Utility;

namespace Sv.Http;

public static class DispatchEndpoints
{
    // 客户端按大小写读取 plat_res.Android，不能套用 ASP.NET 默认的 camelCase。
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web) { PropertyNamingPolicy = null };

    public static void MapDispatchEndpoints(this WebApplication app)
    {
        app.MapMethods("/query_region", ["GET", "POST"], QueryRegion);
        app.MapMethods("/query_gatesvr", ["GET", "POST"], () => Results.Json(new
        {
            code = 200, data = new { gatesvr = new { ip = Config.Server.AdvertiseHost, port = Config.Server.AdvertisePort, ipv6 = Config.Server.AdvertiseIpv6 } },
        }));
    }
    private static IResult QueryRegion()
    {
        ServerOptions server = Config.Server; string local = server.PublicHttpUrl;
        string assets = server.ProxyAssets ? local : server.AssetOrigin.GetLeftPart(UriPartial.Authority);
        return Results.Json(new
        {
            code = 200,
            data = new
            {
                status = 1, time_stamp = Time.Now.ToUnixTimeSeconds(), time_zone = (int)Time.TimeZone.BaseUtcOffset.TotalHours,
                client_info = new { client_version = server.ClientVersion },
                region_info = new[]
                {
                    new
                    {
                        order = 1, region_name = server.Region, region_title = server.RegionTitle,
                        dispatch_url = local, account_url = local, account_url_bak = local, pay_callback_url = "",
                        resource_url = $"{assets}/client_game_res/{server.Region}", resource_url_bak = $"{assets}/client_game_res/{server.Region}",
                        data_url = $"{assets}/client_design_data/{server.Region}", data_url_bak = $"{assets}/client_design_data/{server.Region}",
                        feedback_url = "", bulletin_url = $"{local}/nxx/announcement/index.html", handbook_url = "", hexie_url = $"{local}/filter",
                        client_custom_cfg = new
                        {
                            visitor = false, sdkenv = 0, debugmenu = false, debuglogswitch = (object?)null,
                            disable_update_msgbox_maxsizemb = 20, check_update_cd = 180, disable_stop_server_download = 1,
                            init_download_arr = new[] { 40000, 40100, 40205, 40306, 40407, 60800, 61300, 61400, 62000 },
                            pv_on = 0, disable_check_login_download = 1, check_dlc = 1, disable_redeemcode_ios = 1,
                        },
                        region_res_cfg = new
                        {
                            plat_res = new { Android = Platform("Android", server.ResourceId, server), iOS = Platform("iOS", server.IosResourceId, server) },
                        },
                        region_design_cfg = new
                        {
                            design_data = new[] { new { cfg_id = server.DesignDataId, cfg_version = server.DesignDataVersion, version_suffix = server.DesignDataSuffix } },
                        },
                    },
                },
            },
        }, JsonOptions);
    }
    private static object Platform(string platform, uint resourceId, ServerOptions server) => new
    {
        res_arr = new[] { new { res_id = resourceId, res_version = server.ResourceVersion, version_suffix = server.ResourceSuffix, plat = platform } },
    };
}
