namespace Sv.Game;

public abstract class PlayerLogicBase(Player player)
{
    protected Player Player { get; } = player;
    public virtual void OnCreate() { }
    public virtual void OnLoad() { }
    public virtual void OnLogin() { }
    public virtual void BeforeSave() { }
    protected internal virtual void OnPlayerEventType(PlayerEventType type, int param1 = 0, int param2 = 0, int param3 = 0, object? state = null) { }
}

public sealed class PlayerActionException(int retcode, string message) : Exception(message)
{
    public int Retcode { get; } = retcode;
}
