using Pbplayer;
using PlayerSaveProto;
using Sv.Resources;
using Sv.Resources.Tables;

namespace Sv.Game;

public sealed class GuideLogic(Player player) : PlayerLogicBase(player)
{
    private GuideComp Comp => Player.SaveData.GuideComp;
    public IEnumerable<KeyValuePair<uint, uint>> Guides => Comp.Guides;
    public GetGuideInfoRsp CreateGuideData()
    {
        GetGuideInfoRsp response = new() { Retcode = 1 };
        foreach (var pair in Guides.OrderBy(pair => pair.Key)) response.GuideItems.Add(new GuideItem { GuideId = pair.Key, Status = pair.Value });
        return response;
    }
    public void Start(uint id)
    {
        Validate(id);
        if (!Comp.Guides.ContainsKey(id)) Comp.Guides.Add(id, 1);
    }
    public void Complete(uint id)
    {
        Validate(id); Comp.Guides[id] = 2;
    }
    private static void Validate(uint id)
    {
        if (GameTableCatalog.Instance.GetDataById<GuideData>(id) is null) throw new PlayerActionException(-2, "引导不存在");
    }
}
