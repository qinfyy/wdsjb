using Serilog;
using Sv.Configuration;
using Sv.Database;
using Sv.Gateway;
using Sv.Http;
using Sv.Resources;

WebApplicationBuilder builder = WebApplication.CreateBuilder(args);
Config.Initialize(builder.Configuration, builder.Environment.ContentRootPath);
builder.Host.UseSerilog((context, configuration) => configuration.ReadFrom.Configuration(context.Configuration).WriteTo.Console());
builder.WebHost.UseUrls($"http://0.0.0.0:{Config.Server.HttpPort}");
builder.WebHost.ConfigureKestrel(options => options.Limits.MaxRequestBodySize = 1024 * 1024);
builder.Services.AddSingleton<GatewayRouter>();
builder.Services.AddHostedService<GatewayHostedService>();
builder.Services.AddHttpClient("assets", client => client.Timeout = TimeSpan.FromSeconds(60))
    .ConfigurePrimaryHttpMessageHandler(() => new HttpClientHandler { AllowAutoRedirect = false });
ResourcesLoader.Load(Config.GameData);
GameDatabase.Initialize(Config.Database);
WebApplication app = builder.Build();
app.MapGet("/", () => Results.Json(new { status = "ok", tables = GameTableCatalog.Instance.LoadedTableCount }));
app.MapAccountEndpoints(); app.MapDispatchEndpoints(); app.MapSdkEndpoints(); app.MapAssetProxy();
await app.RunAsync();
