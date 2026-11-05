using PlayerSaveProto;

namespace Sv.Game;

internal static class InitialPlayerTemplate
{
    public static PlayerSaveData CreateSaveData() => new()
    {
        Playerdata = new(), WalletComp = new(), InventoryComp = new(), GuideComp = new(), LevelComp = new(), StoryComp = new(),
    };
}
