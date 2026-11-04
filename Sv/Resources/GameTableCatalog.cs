using System.Collections.Frozen;
using System.Diagnostics.CodeAnalysis;
using Sv.Resources.Tables;

namespace Sv.Resources;

public sealed class GameTableCatalog
{
    private static GameTableCatalog? _instance;
    public static GameTableCatalog Instance
    {
        get => _instance ?? throw new InvalidOperationException("资源表尚未初始化");
        internal set => _instance = value;
    }
    private readonly Dictionary<Type, object> _tables = [];
    private readonly List<TableBase> _rows = [];
    public bool IsLoaded { get; internal set; }
    public int LoadedTableCount => _tables.Count;
    public T? GetDataById<T>(int id) where T : TableBase => GetTable<T>().GetValueOrDefault(id);
    public T? GetDataById<T>(uint id) where T : TableBase => id > int.MaxValue ? null : GetDataById<T>((int)id);
    public bool TryGetDataById<T>(int id, [NotNullWhen(true)] out T? row) where T : TableBase => GetTable<T>().TryGetValue(id, out row);
    public FrozenDictionary<int, T> GetTable<T>() where T : TableBase => (FrozenDictionary<int, T>)_tables[typeof(T)];
    public IReadOnlyList<T> GetAllData<T>() where T : TableBase => GetTable<T>().Values.ToArray();

    internal void PushTable<T>(Dictionary<int, T> rows) where T : TableBase
    {
        if (IsLoaded || !_tables.TryAdd(typeof(T), rows.ToFrozenDictionary())) throw new InvalidOperationException($"表 {typeof(T).Name} 不可重复注册");
        _rows.AddRange(rows.Values);
    }
    public void BroadcastOnFinalize()
    {
        foreach (TableBase row in _rows) row.OnFinalize();
    }
    public void BroadcastVerification()
    {
        foreach (TableBase row in _rows) row.Verification();
    }
}
