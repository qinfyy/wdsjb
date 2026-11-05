namespace Sv.Resources.Tables;

public abstract class TableBase
{
    public abstract int GetId();
    /// <summary>阶段 1：基础反序列化完成后触发，用于字段解析、枚举映射与字段预计算。</summary>
    public virtual void OnLoad() { }
    /// <summary>阶段 2：全部表 OnLoad 完成后触发，直取 GameTableCatalog.Instance 构建关联与二级索引。</summary>
    public virtual void OnFinalize() { }
    /// <summary>阶段 3：全部表关联建立后触发，校验跨表约束、业务边界与资源完整性。</summary>
    public virtual void Verification() { }
}
