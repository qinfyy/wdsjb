using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Sv.Configuration;

namespace Sv.Http;

public static class SdkEndpoints
{
    private static IResult Success(object? data) => Results.Json(new { retcode = 0, message = "OK", data });
    public static void MapSdkEndpoints(this WebApplication app)
    {
        app.MapGet("/_ts", () => Success(new { ts = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() }));
        app.MapMethods("/nxx_cn/mdk/shield/api/loadConfig", ["GET", "POST"], () => Success(new
        {
            id = 8, game_key = "nxx_cn", client = "Android", identity = "I_IDENTITY", guest = false, ignore_versions = "", scene = "S_NORMAL",
            name = "未定事件簿", disable_regist = !Config.Account.AutoCreate, enable_email_captcha = false,
            thirdparty = Array.Empty<object>(), disable_mmt = true, server_guest = false, enable_flash_login = false, enable_age_gate = false,
            thirdparty_ignore = new { }, thirdparty_login_configs = new { }, enable_ps_bind_account = false,
        }));
        app.MapMethods("/nxx_cn/combo/granter/api/getConfig", ["GET", "POST"], () => Success(new
        {
            protocol = false, qr_enabled = false, log_level = "INFO", announce_url = $"{Config.Server.PublicHttpUrl}/nxx/announcement/index.html",
            push_alias_type = 1, disable_ysdk_guard = true, enable_announce_pic_popup = false, app_name = "未定事件簿",
            qr_enabled_apps = (object?)null, qr_app_icons = (object?)null, enable_user_center = false, ugc_protocol = false,
            functional_switch_configs = new { jpush = false }, widget_config = (object?)null,
        }));
        app.MapMethods("/nxx_cn/combo/granter/api/compareProtocolVersion", ["GET", "POST"], () => Success(new { modified = false, protocol = (object?)null }));
        app.MapMethods("/nxx_cn/combo/granter/api/getFont", ["GET", "POST"], () => Success(new { fonts = Array.Empty<object>() }));
        app.MapGet("/combo/box/api/config/porte-cn/porte", () => Success(new
        {
            vals = new { cryptoConfig = JsonSerializer.Serialize(new { downgrade = true, disabledVersionsBelow = 9, disabledDeviceModels = Array.Empty<string>() }) },
        }));
        app.MapGet("/combo/box/api/config/sdk/combo", () => Success(new
        {
            vals = new { enable_attribution = "false", enable_oaid = "false", hotfix_config = "false", login_flow_notification = "{\"enable\":0}" },
        }));
        app.MapGet("/combo/box/api/config/sw/precache", () => Results.Json(new { retcode = 7, message = "RetCode_NoConfig", data = (object?)null }));
        app.MapGet("/nxx_cn/combo/sdkconfig/oaid/api/getConfig", () => Results.Json(new { retcode = -4002, message = "not found", data = (object?)null }));
        app.MapPost("/device-fp/api/getFp", FingerprintAsync);
        app.MapPost("/device-fp/api/getExtList", () => Success(new { code = 200, msg = "ok", ext_list = Array.Empty<string>(), pkg_list = Array.Empty<string>(), pkg_str = "" }));
        app.MapGet("/common/nxx_cn/announcement/api/getAnnList", () => Success(new
        {
            list = Array.Empty<object>(), total = 0, type_list = Array.Empty<object>(), alert = false, alert_id = 0,
            timezone = 8, pic_list = Array.Empty<object>(), pic_total = 0, pic_type_list = Array.Empty<object>(), pic_alert = false, pic_alert_id = 0,
        }));
        app.MapGet("/nxx/announcement/index.html", () => Results.Content("<!doctype html><html lang=\"zh-cn\"><title>Demo</title><body></body></html>", "text/html"));
        app.MapMethods("/ptolemaios_api/api/getPatch", ["GET", "POST"], () => Success(new
        {
            patch_strategy_id = 0, patch_id = 0, patch_version = "", md5 = "", file_url = "", file_name = "", patch_action = 0, update_type = 0,
            dialog_num = 0, dialog_period_type = 0, dialog_period = 0, dialog_title = "", dialog_content = "", im_page_ids = Array.Empty<int>(),
        }));
        foreach (string path in new[] { "/sdk/dataUpload", "/adsdk/dataUpload", "/apm/dataUpload", "/common/h5log/log/batch", "/crashlog", "/uilog" })
            app.MapPost(path, () => Success(null));
        app.MapGet("/sdk_global/apphub/api/getAttributionReportConfig", () => Success(new { enabled = false }));
    }
    private static async Task<IResult> FingerprintAsync(HttpRequest request)
    {
        try
        {
            using JsonDocument body = await JsonDocument.ParseAsync(request.Body, cancellationToken: request.HttpContext.RequestAborted);
            string id = body.RootElement.TryGetProperty("device_id", out JsonElement value) && value.ValueKind == JsonValueKind.String ? value.GetString()! : "demo";
            string fingerprint = Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(id)))[..13];
            return Success(new { device_fp = fingerprint, code = 200, msg = "ok" });
        }
        catch (JsonException) { return Results.Json(new { retcode = -202, message = "无效设备请求", data = (object?)null }); }
    }
}
