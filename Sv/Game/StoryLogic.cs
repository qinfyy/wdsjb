using Pbplayer;
using PlayerSaveProto;
using Sv.Resources;
using Sv.Resources.Tables;

namespace Sv.Game;

public sealed class StoryLogic(Player player) : PlayerLogicBase(player)
{
    private StoryComp Comp => Player.SaveData.StoryComp;
    public IEnumerable<KeyValuePair<uint, uint>> Stories => Comp.Stories;
    public bool Completed(uint id) => Comp.Stories.GetValueOrDefault(id) == 2;
    public GetStoryDataRsp CreateStoryData(uint dataAll = 1, ICollection<uint>? ids = null)
    {
        GetStoryDataRsp response = new() { Retcode = 1, StoryDataAll = dataAll };
        foreach (var pair in Stories.Where(pair => dataAll != 0 || ids is null || ids.Contains(pair.Key)).OrderBy(pair => pair.Key))
            response.StoryList.Add(new StoryItem { StoryId = pair.Key, Status = pair.Value });
        return response;
    }
    public void Complete(uint id)
    {
        if (Completed(id)) return;
        bool available = GameTableCatalog.Instance.GetAllData<LevelData>().Any(row => row.StoryIds.Contains(id) && Player.Level.IsOpen(row.Id));
        if (!available) throw new PlayerActionException(-2, "剧情不存在或尚未解锁");
        Comp.Stories[id] = 2;
    }
}
