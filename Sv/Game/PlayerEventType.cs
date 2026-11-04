namespace Sv.Game;

/// <summary>玩家领域事件，由 Player.Trigger 按 Logic 生命周期顺序分发。</summary>
public enum PlayerEventType
{
    /// <summary>关卡通过，param1 = levelId，param2 = 是否首通，param3 = 玩家经验奖励。</summary>
    LevelPassed = 1,

    /// <summary>关卡结算完成，响应后同步资产与关卡；param1 = levelId，param2 = 是否首通。</summary>
    LevelSettled = 2,
    MainDataChanged,
    CardsChanged,
    DecksChanged,
    MaterialsChanged,
    WalletChanged,
    TicketsChanged,
    LevelsChanged,
}
