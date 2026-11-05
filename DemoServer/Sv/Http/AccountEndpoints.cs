using System.Text.Json;
using System.Text.Json.Serialization;
using Microsoft.AspNetCore.Mvc;
using Sv.Configuration;
using Sv.Database;

namespace Sv.Http;

public static class AccountEndpoints
{
    private static readonly JsonSerializerOptions RequestJsonOptions = new()
    {
        PropertyNameCaseInsensitive = true,
    };

    public static void MapAccountEndpoints(this WebApplication app)
    {
        app.MapPost("/account/ma-cn-passport/app/loginByMobileCaptcha", LoginByMobileCaptchaAsync);
        app.MapPost("/account/ma-cn-passport/app/loginByPassword", LoginByPasswordAsync);
        app.MapPost("/account/ma-cn-session/app/verify", VerifyAsync);
        app.MapPost("/account/ma-cn-session/app/getUserInfo", GetUserInfoAsync);
        app.MapPost("/account/ma-cn-session/app/exchange", ExchangeAsync);
        app.MapPost("/nxx_cn/combo/granter/login/v2/login", ComboLoginAsync);
    }

    private static IResult LoginByMobileCaptchaAsync([FromBody] MobileCaptchaLoginRequest? request)
    {
        if (request is null)
        {
            return Error(-202, "登录请求格式错误");
        }

        try
        {
            AccountTokenResult result = GameDatabase.Instance.LoginAccountByMobileCaptcha(request.Mobile, request.AreaCode, request.Captcha, Config.Account.AutoCreate);
            return LoginSuccess(result);
        }
        catch (AccountIdentityException exception)
        {
            return Error(exception.Retcode, exception.Message);
        }
    }

    private static IResult LoginByPasswordAsync([FromBody] PasswordLoginRequest? request)
    {
        if (request is null)
        {
            return Error(-202, "登录请求格式错误");
        }

        try
        {
            AccountTokenResult result = GameDatabase.Instance.LoginAccountByPassword(request.Account, request.Password, Config.Account.AutoCreate, Config.Account.VerifyPassword);
            return LoginSuccess(result);
        }
        catch (AccountIdentityException exception)
        {
            return Error(exception.Retcode, exception.Message);
        }
    }

    private static IResult VerifyAsync([FromBody] SessionVerifyRequest? request)
    {
        if (request?.Token is null)
        {
            return Error(-202, "登录请求格式错误");
        }

        try
        {
            AccountVerifyResult result = GameDatabase.Instance.VerifyAccountSession(request.Mid, request.Token.TokenType, request.Token.Token, request.Refresh);
            object? newToken = result.NewToken is null ? null : new
            {
                token_type = result.NewToken.TokenType,
                token = result.NewToken.Token,
            };

            return Results.Json(new
            {
                retcode = 0,
                message = "OK",
                data = new
                {
                    user_info = CreateUserInfo(result.Account),
                    realname_info = CreateRealnameInfo(),
                    need_realperson = false,
                    new_token = newToken,
                },
            });
        }
        catch (AccountIdentityException exception)
        {
            return Error(exception.Retcode, exception.Message);
        }
    }

    private static IResult GetUserInfoAsync([FromBody] SessionVerifyRequest? request)
    {
        if (request?.Token is null) return Error(-202, "登录请求格式错误");
        try
        {
            AccountVerifyResult result = GameDatabase.Instance.VerifyAccountSession(request.Mid, request.Token.TokenType, request.Token.Token, refresh: false);
            return Results.Json(new
            {
                retcode = 0, message = "OK",
                data = new { user_info = CreateUserInfo(result.Account), realname_info = CreateRealnameInfo(), need_realperson = false, game_ctrl_info = (object?)null },
            });
        }
        catch (AccountIdentityException exception) { return Error(exception.Retcode, exception.Message); }
    }

    private static IResult ExchangeAsync([FromBody] SessionExchangeRequest? request)
    {
        if (request?.SourceToken is null)
        {
            return Error(-202, "登录请求格式错误");
        }

        try
        {
            AccountTokenResult result = GameDatabase.Instance.ExchangeAccountToken(request.Mid, request.SourceToken.TokenType, request.SourceToken.Token, request.DestinationTokenType);
            return Results.Json(new
            {
                retcode = 0,
                message = "OK",
                data = new
                {
                    token = new
                    {
                        token_type = result.TokenType,
                        token = result.Token,
                    },
                    user_info = CreateUserInfo(result.Account),
                    expire_in_seconds = "172800",
                },
            });
        }
        catch (AccountIdentityException exception)
        {
            return Error(exception.Retcode, exception.Message);
        }
    }

    private static IResult ComboLoginAsync([FromBody] ComboLoginRequest? request)
    {
        if (request is null)
        {
            return Error(-202, "登录请求格式错误");
        }

        ComboLoginData? loginData;
        try
        {
            loginData = JsonSerializer.Deserialize<ComboLoginData>(request.Data ?? string.Empty, RequestJsonOptions);
        }
        catch (JsonException)
        {
            return Error(-202, "Combo 登录数据格式错误");
        }

        if (loginData is null)
        {
            return Error(-202, "Combo 登录数据格式错误");
        }

        try
        {
            AccountComboResult result = GameDatabase.Instance.GrantAccountComboToken(loginData.Uid, loginData.Token, request.ChannelId);
            return Results.Json(new
            {
                retcode = 0,
                message = "OK",
                data = new
                {
                    combo_id = "0",
                    open_id = result.Account.Aid,
                    combo_token = result.ComboToken,
                    data = "{\"guest\":false}",
                    heartbeat = false,
                    account_type = 1,
                    fatigue_remind = (object?)null,
                },
            });
        }
        catch (AccountIdentityException exception)
        {
            return Error(exception.Retcode, exception.Message);
        }
    }

    private static IResult LoginSuccess(AccountTokenResult result) => Results.Json(new
    {
        retcode = 0,
        message = "OK",
        data = new
        {
            token = new
            {
                token_type = result.TokenType,
                token = result.Token,
            },
            user_info = CreateUserInfo(result.Account),
            reactivate_info = new
            {
                required = false,
                ticket = string.Empty,
                deleting_biz_account = false,
                reactivate_biz = string.Empty,
                delete_after_days = "0",
            },
            login_ticket = string.Empty,
            new_user = result.IsNewAccount,
            realname_info = CreateRealnameInfo(),
            need_realperson = false,
            oauth_hw_open_id = string.Empty,
        },
    });

    private static object CreateUserInfo(AccountProfile account) => new
    {
        aid = account.Aid,
        mid = account.Aid,
        account_name = account.AccountName,
        email = account.Email,
        is_email_verify = account.Email.Length == 0 ? 0 : 1,
        area_code = account.AreaCode,
        mobile = account.Mobile,
        safe_area_code = string.Empty,
        safe_mobile = string.Empty,
        realname = "Demo",
        identity_code = "******************",
        rebind_area_code = string.Empty,
        rebind_mobile = string.Empty,
        rebind_mobile_time = "0",
        links = Array.Empty<object>(),
        country = string.Empty,
        password_time = "0",
        is_adult = 1,
        unmasked_email = string.Empty,
        unmasked_email_type = 0,
    };

    private static object CreateRealnameInfo() => new
    {
        required = false,
        action_type = string.Empty,
        action_ticket = string.Empty,
    };

    private static IResult Error(int retcode, string message) => Results.Json(new { retcode, message, data = (object?)null, });


    private sealed class MobileCaptchaLoginRequest
    {
        [JsonPropertyName("mobile")]
        public string Mobile { get; init; } = string.Empty;

        [JsonPropertyName("captcha")]
        public string Captcha { get; init; } = string.Empty;

        [JsonPropertyName("action_type")]
        public string ActionType { get; init; } = string.Empty;

        [JsonPropertyName("area_code")]
        public string AreaCode { get; init; } = string.Empty;
    }

    private sealed class PasswordLoginRequest
    {
        [JsonPropertyName("account")]
        public string Account { get; init; } = string.Empty;

        [JsonPropertyName("password")]
        public string Password { get; init; } = string.Empty;
    }

    private sealed class SdkToken
    {
        [JsonPropertyName("token")]
        public string Token { get; init; } = string.Empty;

        [JsonPropertyName("token_type")]
        public int TokenType { get; init; }
    }

    private sealed class SessionVerifyRequest
    {
        [JsonPropertyName("mid")]
        public string Mid { get; init; } = string.Empty;

        [JsonPropertyName("refresh")]
        public bool Refresh { get; init; }

        [JsonPropertyName("token")]
        public SdkToken? Token { get; init; }
    }

    private sealed class SessionExchangeRequest
    {
        [JsonPropertyName("src_token")]
        public SdkToken? SourceToken { get; init; }

        [JsonPropertyName("mid")]
        public string Mid { get; init; } = string.Empty;

        [JsonPropertyName("dst_token_type")]
        public int DestinationTokenType { get; init; }
    }

    private sealed class ComboLoginRequest
    {
        [JsonPropertyName("data")]
        public string Data { get; init; } = string.Empty;

        [JsonPropertyName("sign")]
        public string Sign { get; init; } = string.Empty;

        [JsonPropertyName("app_id")]
        public int AppId { get; init; }

        [JsonPropertyName("channel_id")]
        public int ChannelId { get; init; }

        [JsonPropertyName("device")]
        public string Device { get; init; } = string.Empty;
    }

    private sealed class ComboLoginData
    {
        [JsonPropertyName("uid")]
        public string Uid { get; init; } = string.Empty;

        [JsonPropertyName("token")]
        public string Token { get; init; } = string.Empty;

        [JsonPropertyName("guest")]
        public bool Guest { get; init; }

        [JsonPropertyName("is_new_register")]
        public bool IsNewRegister { get; init; }
    }
}
