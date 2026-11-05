using System.Collections;
using System.Reflection;
using Google.Protobuf;
using Google.Protobuf.Reflection;

namespace Sv.Gateway;

internal sealed class ProtoFallbackHandler
{
    private readonly Dictionary<ushort, (Type RequestType, Type ResponseType, ushort ResponseCmdId)> _endpoints = CreateEndpoints();

    public bool CanHandle(ushort commandId) => _endpoints.ContainsKey(commandId);

    public void Handle(GatewaySession session, ushort commandId, byte[] body)
    {
        if (!_endpoints.TryGetValue(commandId, out var endpoint)) throw new InvalidOperationException($"Proto 命令 {commandId} 未找到响应定义");
        IMessage request = (IMessage)(Activator.CreateInstance(endpoint.RequestType) ?? throw new InvalidOperationException($"无法实例化请求 {endpoint.RequestType.FullName}"));
        request.MergeFrom(new CodedInputStream(body));
        IMessage response = (IMessage)(Activator.CreateInstance(endpoint.ResponseType) ?? throw new InvalidOperationException(
            $"无法实例化响应 {endpoint.ResponseType.FullName}"));
        CopyRequestFields(request, response);
        SetSuccessCode(response);
        session.Send(endpoint.ResponseCmdId, response, session.RequestHead);
    }

    private static Dictionary<ushort, (Type RequestType, Type ResponseType, ushort ResponseCmdId)> CreateEndpoints()
    {
        Type[] messageTypes = typeof(Pbmisc.PingReq).Assembly.GetTypes()
            .Where(type => type.IsClass && !type.IsAbstract && typeof(IMessage).IsAssignableFrom(type))
            .ToArray();
        Dictionary<string, Type> byName = messageTypes.ToDictionary(type => $"{type.Namespace}|{type.Name}");
        Dictionary<ushort, (Type RequestType, Type ResponseType, ushort ResponseCmdId)> endpoints = [];
        foreach (Type requestType in messageTypes.Where(type => type.Name.EndsWith("Req", StringComparison.Ordinal)))
        {
            string responseName = $"{requestType.Name[..^3]}Rsp";
            if (!byName.TryGetValue($"{requestType.Namespace}|{responseName}", out Type? responseType)) continue;
            ushort? requestCommand = GetCommandId(requestType);
            ushort? responseCommand = GetCommandId(responseType);
            if (requestCommand is null || responseCommand is null) continue;
            endpoints.TryAdd(requestCommand.Value, (requestType, responseType, responseCommand.Value));
        }
        return endpoints;
    }

    private static ushort? GetCommandId(Type messageType)
    {
        Type? types = messageType.GetNestedType("Types", BindingFlags.Public);
        Type? commandType = types?.GetNestedType("CmdId", BindingFlags.Public) ?? messageType.GetNestedType("CmdId", BindingFlags.Public);
        FieldInfo? commandField = commandType?.GetField("CmdId", BindingFlags.Public | BindingFlags.Static)
            ?? commandType?.GetField("CMD_ID", BindingFlags.Public | BindingFlags.Static);
        object? rawValue = commandField?.GetRawConstantValue();
        if (rawValue is null) return null;
        int value = Convert.ToInt32(rawValue);
        return value is >= 0 and <= ushort.MaxValue ? (ushort)value : null;
    }

    private static void CopyRequestFields(IMessage request, IMessage response)
    {
        foreach (FieldDescriptor source in request.Descriptor.Fields.InFieldNumberOrder())
        {
            FieldDescriptor? target = response.Descriptor.FindFieldByName(source.Name);
            if (target is null || target.FieldType != source.FieldType || target.IsRepeated != source.IsRepeated || target.IsMap != source.IsMap) continue;
            if (source.FieldType is FieldType.Message or FieldType.Group || source.FieldType == FieldType.Enum && source.EnumType != target.EnumType) continue;
            if (source.IsMap) continue;
            if (source.IsRepeated)
            {
                if (source.Accessor.GetValue(request) is not IEnumerable values || target.Accessor.GetValue(response) is not IList targetValues) continue;
                foreach (object? value in values) if (value is not null) targetValues.Add(value);
                continue;
            }
            object? scalar = source.Accessor.GetValue(request);
            if (scalar is not null) target.Accessor.SetValue(response, scalar);
        }
    }

    private static void SetSuccessCode(IMessage response)
    {
        FieldDescriptor? retcode = response.Descriptor.FindFieldByName("retcode");
        if (retcode is not null && !retcode.IsRepeated && retcode.FieldType == FieldType.Int32) retcode.Accessor.SetValue(response, 1);
    }
}
