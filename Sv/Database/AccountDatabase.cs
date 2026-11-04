using System.Security.Cryptography;
using Microsoft.EntityFrameworkCore;
using Sv.Utility;

namespace Sv.Database;

public sealed record AccountProfile(string Aid, string AccountName, string Email, string AreaCode, string Mobile);

public sealed record AccountTokenResult(AccountProfile Account, int TokenType, string Token, bool IsNewAccount);

public sealed record AccountVerifyResult(AccountProfile Account, AccountTokenResult? NewToken);

public sealed record AccountComboResult(AccountProfile Account, string ComboToken);

public sealed record ManagedAccountProfile(string Aid, string? Username, string? Mobile, bool HasPassword, DateTimeOffset CreatedAt, DateTimeOffset UpdatedAt);

public sealed class AccountIdentityException(int retcode, string message) : Exception(message)
{
    public int Retcode { get; } = retcode;
}

public sealed partial class GameDatabase
{
    private const int SessionTokenType = 1;
    private const int GameTokenType = 4;
    private static readonly TimeSpan SessionTokenLifetime = TimeSpan.FromDays(30);
    private static readonly TimeSpan GameTokenLifetime = TimeSpan.FromDays(2);
    private static readonly TimeSpan ComboTokenLifetime = TimeSpan.FromDays(2);

    public AccountTokenResult LoginAccountByMobileCaptcha(string mobile, string areaCode, string captcha, bool autoCreate = true)
    {
        mobile = NormalizeRequired(mobile, "手机号", 512);
        areaCode = NormalizeRequired(areaCode, "区号", 512);
        _ = NormalizeRequired(captcha, "短信验证码", 32);

        lock (_writeLock)
        {
            using GameDbContext db = CreateDbContext();
            AccountEntity? entity = db.Accounts.SingleOrDefault(value => value.Mobile == mobile);
            bool isNew = entity is null;
            if (entity is null)
            {
                if (!autoCreate)
                {
                    throw new AccountIdentityException(-201, "账号不存在，请联系管理员创建");
                }
                entity = CreateAccount(db, username: null, mobile, areaCode);
            }
            else
            {
                entity.AreaCode = areaCode;
            }

            string token = IssueSessionToken(entity);
            TouchLogin(entity);
            db.SaveChanges();
            return new AccountTokenResult(ToProfile(entity), SessionTokenType, token, isNew);
        }
    }

    public AccountTokenResult LoginAccountByPassword(string account, string password, bool autoCreate = true, bool verifyPassword = true)
    {
        account = NormalizeRequired(account, "账号", 512);
        password = password?.Trim() ?? string.Empty;
        if (password.Length > 1024)
        {
            throw new AccountIdentityException(-202, "密码长度超过限制");
        }

        lock (_writeLock)
        {
            using GameDbContext db = CreateDbContext();
            AccountEntity? entity = db.Accounts.SingleOrDefault(value => value.Username == account || value.Mobile == account);
            bool isNew = entity is null;
            if (entity is null)
            {
                if (!autoCreate)
                {
                    throw new AccountIdentityException(-201, "账号不存在，请联系管理员创建");
                }
                entity = CreateAccount(db, account, mobile: null, areaCode: string.Empty);
                if (password.Length > 0)
                {
                    SetPassword(entity, password);
                }
            }
            else if (verifyPassword && entity.Password is not null && !string.Equals(entity.Password, password, StringComparison.Ordinal))
            {
                throw new AccountIdentityException(-201, "账号或密码错误");
            }

            string token = IssueSessionToken(entity);
            TouchLogin(entity);
            db.SaveChanges();
            return new AccountTokenResult(ToProfile(entity), SessionTokenType, token, isNew);
        }
    }

    public AccountVerifyResult VerifyAccountSession(string mid, int tokenType, string token, bool refresh)
    {
        mid = NormalizeRequired(mid, "MID", 32);
        token = NormalizeRequired(token, "登录令牌", 512);

        lock (_writeLock)
        {
            using GameDbContext db = CreateDbContext();
            AccountEntity entity = FindByMid(db, mid);
            ValidateToken(entity, tokenType, token);

            AccountTokenResult? newToken = null;
            if (refresh && entity.SessionTokenExpiresAt <= Time.Now.AddDays(7))
            {
                string refreshed = IssueSessionToken(entity);
                newToken = new AccountTokenResult(ToProfile(entity), SessionTokenType, refreshed, IsNewAccount: false);
            }

            entity.UpdatedAt = Time.Now;
            db.SaveChanges();
            return new AccountVerifyResult(ToProfile(entity), newToken);
        }
    }

    public AccountTokenResult ExchangeAccountToken(string mid, int sourceTokenType, string sourceToken, int destinationTokenType)
    {
        mid = NormalizeRequired(mid, "MID", 32);
        sourceToken = NormalizeRequired(sourceToken, "源令牌", 512);
        if (destinationTokenType != GameTokenType)
        {
            throw new AccountIdentityException(-202, "不支持的目标令牌类型");
        }

        lock (_writeLock)
        {
            using GameDbContext db = CreateDbContext();
            AccountEntity entity = FindByMid(db, mid);
            ValidateToken(entity, sourceTokenType, sourceToken);
            string token = GenerateOpaqueToken(64);
            entity.GameToken = token;
            entity.GameTokenExpiresAt = Time.Now.Add(GameTokenLifetime);
            entity.UpdatedAt = Time.Now;
            db.SaveChanges();
            return new AccountTokenResult(ToProfile(entity), GameTokenType, token, IsNewAccount: false);
        }
    }

    public AccountComboResult GrantAccountComboToken(string aid, string gameToken, int channelId)
    {
        aid = NormalizeRequired(aid, "AID", 32);
        gameToken = NormalizeRequired(gameToken, "游戏令牌", 512);
        if (channelId <= 0)
        {
            throw new AccountIdentityException(-202, "ChannelId 无效");
        }

        lock (_writeLock)
        {
            using GameDbContext db = CreateDbContext();
            if (!long.TryParse(aid, out long aidValue) || aidValue <= 0)
            {
                throw new AccountIdentityException(-202, "AID 无效");
            }
            AccountEntity entity = db.Accounts.SingleOrDefault(value => value.Aid == aidValue) ?? throw new AccountIdentityException(-201, "账号缓存信息错误");
            // 官服 Combo 请求直接复用登录接口返回的 type 1 会话令牌；部分流程
            // 也会先 exchange 为 type 4，因此两种令牌都必须接受。
            ValidateSessionOrGameToken(entity, gameToken);

            string comboToken = GenerateOpaqueToken(32);
            entity.ComboToken = comboToken;
            entity.ComboTokenExpiresAt = Time.Now.Add(ComboTokenLifetime);
            entity.ComboChannelId = channelId;
            entity.UpdatedAt = Time.Now;
            db.SaveChanges();
            return new AccountComboResult(ToProfile(entity), comboToken);
        }
    }

    public bool ValidateAccountComboToken(int channelId, string aid, string comboToken)
    {
        if (channelId <= 0 || string.IsNullOrWhiteSpace(aid) || string.IsNullOrWhiteSpace(comboToken))
        {
            return false;
        }

        using GameDbContext db = CreateDbContext();
        if (!long.TryParse(aid, out long aidValue) || aidValue <= 0)
        {
            return false;
        }
        AccountEntity? entity = db.Accounts.AsNoTracking().SingleOrDefault(value => value.Aid == aidValue);
        return entity is not null &&
            entity.ComboChannelId == channelId &&
            entity.ComboTokenExpiresAt > Time.Now &&
            TokenMatches(entity.ComboToken, comboToken);
    }

    public ManagedAccountProfile CreateManagedAccount(string? username, string? password, string? mobile)
    {
        username = NormalizeOptional(username, "用户名", 512);
        mobile = NormalizeManagedMobile(mobile, required: false);
        password = password?.Trim();
        if (username is null && mobile is null)
        {
            throw new AccountIdentityException(-202, "username 和 mobile 必须至少提供一个");
        }
        if (!string.IsNullOrEmpty(password) && username is null)
        {
            throw new AccountIdentityException(-202, "设置密码时必须提供 username");
        }
        if (password?.Length > 1024)
        {
            throw new AccountIdentityException(-202, "密码长度超过限制");
        }

        lock (_writeLock)
        {
            using GameDbContext db = CreateDbContext();
            EnsureAccountFieldsAvailable(db, username, mobile, exceptAid: null);
            AccountEntity entity = CreateAccount(db, username, mobile, areaCode: string.Empty);
            if (!string.IsNullOrEmpty(password))
            {
                SetPassword(entity, password);
            }
            db.SaveChanges();
            return ToManagedProfile(entity);
        }
    }

    public ManagedAccountProfile UpdateManagedAccount(string query, bool updateUsername, string? newUsername, bool updatePassword, string? newPassword, bool updateMobile, string? newMobile)
    {
        query = NormalizeRequired(query, "query", 512);
        if (!updateUsername && !updatePassword && !updateMobile)
        {
            throw new AccountIdentityException(-202, "至少提供 newusername、newpassward 或 newmobile 之一");
        }

        newUsername = updateUsername ? NormalizeOptional(newUsername, "新用户名", 512) : null;
        newMobile = updateMobile ? NormalizeManagedMobile(newMobile, required: false) : null;
        newPassword = updatePassword ? newPassword?.Trim() : null;
        if (newPassword?.Length > 1024)
        {
            throw new AccountIdentityException(-202, "新密码长度超过限制");
        }

        lock (_writeLock)
        {
            using GameDbContext db = CreateDbContext();
            AccountEntity entity = FindManagedAccount(db, query);
            string? finalUsername = updateUsername ? newUsername : entity.Username;
            string? finalMobile = updateMobile ? newMobile : entity.Mobile;
            if (finalUsername is null && finalMobile is null)
            {
                throw new AccountIdentityException(-202, "username 和 mobile 不能同时为空");
            }
            if (updatePassword && !string.IsNullOrEmpty(newPassword) && finalUsername is null)
            {
                throw new AccountIdentityException(-202, "设置密码时账号必须具有 username");
            }

            EnsureAccountFieldsAvailable(db, finalUsername, finalMobile, entity.Aid);
            entity.Username = finalUsername;
            entity.Mobile = finalMobile;
            if (updatePassword)
            {
                if (string.IsNullOrEmpty(newPassword))
                {
                    entity.Password = null;
                }
                else
                {
                    SetPassword(entity, newPassword);
                }
            }
            InvalidateTokens(entity);
            entity.UpdatedAt = Time.Now;
            db.SaveChanges();
            return ToManagedProfile(entity);
        }
    }

    public ManagedAccountProfile DeleteManagedAccount(string query)
    {
        query = NormalizeRequired(query, "query", 512);
        lock (_writeLock)
        {
            using GameDbContext db = CreateDbContext();
            AccountEntity entity = FindManagedAccount(db, query);
            ManagedAccountProfile deleted = ToManagedProfile(entity);
            string aid = entity.Aid.ToString();
            PlayerEntity[] players = db.Players.Where(value => value.OpenId == aid).ToArray();
            db.Players.RemoveRange(players);
            db.Accounts.Remove(entity);
            db.SaveChanges();
            return deleted;
        }
    }

    private static AccountEntity CreateAccount(GameDbContext db, string? username, string? mobile, string areaCode)
    {
        DateTimeOffset now = Time.Now;
        AccountEntity entity = new()
        {
            Username = username,
            Mobile = mobile,
            AreaCode = areaCode,
            CreatedAt = now,
            UpdatedAt = now,
            LastLoginAt = now,
        };
        db.Accounts.Add(entity);
        return entity;
    }

    private static string IssueSessionToken(AccountEntity entity)
    {
        string token = GenerateOpaqueToken(64);
        entity.SessionToken = token;
        entity.SessionTokenExpiresAt = Time.Now.Add(SessionTokenLifetime);
        return token;
    }

    private static void ValidateToken(AccountEntity entity, int tokenType, string token)
    {
        (string? Token, DateTimeOffset? ExpiresAt) stored = tokenType switch
        {
            SessionTokenType => (entity.SessionToken, entity.SessionTokenExpiresAt),
            GameTokenType => (entity.GameToken, entity.GameTokenExpiresAt),
            _ => throw new AccountIdentityException(-202, "不支持的令牌类型"),
        };
        if (stored.ExpiresAt is null || stored.ExpiresAt <= Time.Now || !TokenMatches(stored.Token, token))
        {
            throw new AccountIdentityException(-201, "账号缓存信息错误");
        }
    }

    private static void ValidateSessionOrGameToken(AccountEntity entity, string token)
    {
        DateTimeOffset now = Time.Now;
        bool sessionValid = entity.SessionTokenExpiresAt > now && TokenMatches(entity.SessionToken, token);
        bool gameValid = entity.GameTokenExpiresAt > now && TokenMatches(entity.GameToken, token);
        if (!sessionValid && !gameValid)
        {
            throw new AccountIdentityException(-201, "账号缓存信息错误");
        }
    }

    private static AccountEntity FindByMid(GameDbContext db, string mid) =>
        db.Accounts.SingleOrDefault(value => value.Aid.ToString() == mid) ?? throw new AccountIdentityException(-201, "账号缓存信息错误");

    private static AccountProfile ToProfile(AccountEntity entity)
    {
        string username = entity.Username ?? string.Empty;
        bool isEmail = username.Contains('@', StringComparison.Ordinal);
        return new AccountProfile(
            entity.Aid.ToString(),
            isEmail ? string.Empty : username,
            isEmail ? username : string.Empty,
            entity.AreaCode,
            entity.Mobile ?? string.Empty);
    }

    private static ManagedAccountProfile ToManagedProfile(AccountEntity entity) =>
        new(entity.Aid.ToString(),
            entity.Username,
            entity.Mobile,
            entity.Password is not null,
            entity.CreatedAt,
            entity.UpdatedAt
        );

    private static AccountEntity FindManagedAccount(GameDbContext db, string query) =>
        db.Accounts.SingleOrDefault(value => value.Username == query || value.Mobile == query) ?? throw new KeyNotFoundException("账号不存在");

    private static void EnsureAccountFieldsAvailable(GameDbContext db, string? username, string? mobile, long? exceptAid)
    {
        if (username is not null && db.Accounts.Any(value => value.Username == username && value.Aid != exceptAid))
        {
            throw new AccountIdentityException(-202, "用户名已存在");
        }
        if (mobile is not null && db.Accounts.Any(value => value.Mobile == mobile && value.Aid != exceptAid))
        {
            throw new AccountIdentityException(-202, "手机号已存在");
        }
    }

    private static void InvalidateTokens(AccountEntity entity)
    {
        entity.SessionToken = null;
        entity.SessionTokenExpiresAt = null;
        entity.GameToken = null;
        entity.GameTokenExpiresAt = null;
        entity.ComboToken = null;
        entity.ComboTokenExpiresAt = null;
        entity.ComboChannelId = 0;
    }

    private static void SetPassword(AccountEntity entity, string password)
    {
        entity.Password = password;
    }

    private static string GenerateOpaqueToken(int charCount)
    {
        if (charCount < 0)
        {
            throw new ArgumentOutOfRangeException(nameof(charCount), "字符数不能为负");
        }

        int byteCount = (charCount + 1) / 2;
        byte[] buffer = RandomNumberGenerator.GetBytes(byteCount);
        string hex = Convert.ToHexString(buffer).ToLowerInvariant();
        return charCount % 2 == 0 ? hex : hex[..^1];
    }

    private static bool TokenMatches(string? expected, string token)
    {
        if (expected is null) return false;
        return CryptographicOperations.FixedTimeEquals(System.Text.Encoding.UTF8.GetBytes(expected), System.Text.Encoding.UTF8.GetBytes(token));
    }

    private static void TouchLogin(AccountEntity entity)
    {
        DateTimeOffset now = Time.Now;
        entity.LastLoginAt = now;
        entity.UpdatedAt = now;
    }

    private static string NormalizeRequired(string? value, string name, int maximumLength)
    {
        string normalized = value?.Trim() ?? string.Empty;
        if (normalized.Length == 0)
        {
            throw new AccountIdentityException(-202, $"{name}不能为空");
        }

        if (normalized.Length > maximumLength)
        {
            throw new AccountIdentityException(-202, $"{name}长度超过限制");
        }

        return normalized;
    }

    private static string? NormalizeOptional(string? value, string name, int maximumLength)
    {
        string normalized = value?.Trim() ?? string.Empty;
        if (normalized.Length > maximumLength)
        {
            throw new AccountIdentityException(-202, $"{name}长度超过限制");
        }
        return normalized.Length == 0 ? null : normalized;
    }

    private static string? NormalizeManagedMobile(string? value, bool required)
    {
        string? normalized = NormalizeOptional(value, "手机号", 512);
        if (normalized is null)
        {
            if (required)
            {
                throw new AccountIdentityException(-202, "手机号不能为空");
            }
            return null;
        }

        if (normalized.Length != 11 || normalized.Any(character => character is < '0' or > '9'))
        {
            throw new AccountIdentityException(-202, "手机号必须是11位数字");
        }

        return normalized;
    }
}
