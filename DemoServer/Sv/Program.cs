using Serilog;
using Sv.Configuration;
using Sv.Database;
using Sv.Gateway;
using Sv.Http;
using Sv.Resources;

Log.Logger = new LoggerConfiguration()
    .MinimumLevel.Information()
    .Enrich.FromLogContext()
    .WriteTo.Console()
    .WriteTo.File(Path.Combine(Directory.GetCurrentDirectory(), "logs", "sv-.log"), rollingInterval: RollingInterval.Day, retainedFileCountLimit: 14)
    .CreateLogger();

try
{
    WebApplicationBuilder builder = WebApplication.CreateBuilder(args);
    Config.Initialize(builder.Configuration, builder.Environment.ContentRootPath);
    Log.Logger = new LoggerConfiguration()
        .ReadFrom.Configuration(builder.Configuration)
        .Enrich.FromLogContext()
        .WriteTo.Console()
        .WriteTo.File(Path.Combine(Directory.GetCurrentDirectory(), "logs", "sv-.log"), rollingInterval: RollingInterval.Day, retainedFileCountLimit: 14)
        .CreateLogger();
    builder.Host.UseSerilog();
    builder.WebHost.UseUrls($"http://0.0.0.0:{Config.Server.HttpPort}");
    builder.WebHost.ConfigureKestrel(options => options.Limits.MaxRequestBodySize = 1024 * 1024);
    builder.Services.AddHostedService<GatewayHostedService>();
    builder.Services.AddHttpClient("assets", client => client.Timeout = TimeSpan.FromSeconds(60))
        .ConfigurePrimaryHttpMessageHandler(() => new HttpClientHandler { AllowAutoRedirect = false });
    ResourcesLoader.Load(Config.GameData);
    GameDatabase.Initialize(Config.Database);
    WebApplication app = builder.Build();
    app.UseSerilogRequestLogging();
    app.MapGet("/", () => Results.Json(new { status = "ok", tables = GameTableCatalog.Instance.LoadedTableCount }));
    app.MapAccountEndpoints(); app.MapDispatchEndpoints(); app.MapSdkEndpoints(); app.MapAssetProxy();
    await app.RunAsync();
}
catch (Exception exception)
{
    Log.Fatal(exception, "服务器异常终止");
}
finally
{
    await Log.CloseAndFlushAsync();
}
