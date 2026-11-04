using System.Net;
using Sv.Configuration;

namespace Sv.Http;

public static class StaticProxy
{
    public static void MapAssetProxy(this WebApplication app)
    {
        foreach (string prefix in new[] { "/client_game_res/{**path}", "/client_design_data/{**path}", "/client_pv/{**path}" })
            app.MapMethods(prefix, ["GET", "HEAD"], ProxyAsync);
    }
    private static async Task ProxyAsync(HttpContext context, IHttpClientFactory factory)
    {
        if (!Config.Server.ProxyAssets) { context.Response.StatusCode = 404; return; }
        Uri origin = Config.Server.AssetOrigin;
        Uri target = new(origin, context.Request.Path.Value + context.Request.QueryString.Value);
        if (target.Host != origin.Host || target.Scheme != origin.Scheme || target.Port != origin.Port)
        {
            context.Response.StatusCode = 400; return;
        }
        using HttpRequestMessage request = new(new HttpMethod(context.Request.Method), target);
        foreach (string name in new[] { "Range", "If-None-Match", "If-Modified-Since" })
            if (context.Request.Headers.TryGetValue(name, out var value)) request.Headers.TryAddWithoutValidation(name, value.ToArray());
        try
        {
            using HttpResponseMessage response = await factory.CreateClient("assets").SendAsync(request, HttpCompletionOption.ResponseHeadersRead, context.RequestAborted);
            if (response.StatusCode is >= HttpStatusCode.MultipleChoices and <= HttpStatusCode.PermanentRedirect)
            {
                context.Response.StatusCode = 502; return;
            }
            context.Response.StatusCode = (int)response.StatusCode;
            foreach (string name in new[] { "ETag", "Last-Modified", "Accept-Ranges", "Content-Range", "Cache-Control", "Content-Type", "Content-Length" })
            {
                if (response.Headers.TryGetValues(name, out var values) || response.Content.Headers.TryGetValues(name, out values))
                    context.Response.Headers[name] = values.ToArray();
            }
            if (!HttpMethods.IsHead(context.Request.Method)) await response.Content.CopyToAsync(context.Response.Body, context.RequestAborted);
        }
        catch (HttpRequestException) { if (!context.Response.HasStarted) context.Response.StatusCode = 502; }
        catch (OperationCanceledException) when (!context.RequestAborted.IsCancellationRequested)
        {
            if (!context.Response.HasStarted) context.Response.StatusCode = 504;
        }
    }
}
