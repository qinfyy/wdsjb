using System.Buffers.Binary;
using System.Net;
using System.Net.Sockets;
using System.Reflection;
using Baseproto;
using Google.Protobuf;
using Microsoft.Data.Sqlite;
using Pbplayer;
using PlayerSaveProto;
using Sv.Configuration;
using Sv.Database;
using Sv.Game;
using Sv.Gateway;
using Sv.Gateway.Protocol;
using Sv.Resources;
using Sv.Resources.Tables;
using Xunit;

namespace Sv.Tests;

[CollectionDefinition("Server", DisableParallelization = true)]
public sealed class ServerCollection : ICollectionFixture<ServerFixture> { }

[Collection("Server")]
public sealed class PlayerEventTests(ServerFixture fixture)
{
    private static Player CreatePlayer() => GameDatabase.Instance.GetOrCreateByAccount(1, Guid.NewGuid().ToString("N"));

    [Fact]
    public void StorageUsesPlayerSaveProtoAndOfflineEventsRemainSafe()
    {
        Player player = CreatePlayer();
        Assert.Equal("PlayerSaveProto.PlayerSaveData", PlayerSaveData.Descriptor.FullName);
        Assert.Equal(2, PlayerSaveData.Descriptor.FindFieldByName("playerdata").FieldNumber);
        foreach (var field in PlayerSaveData.Descriptor.Fields.InFieldNumberOrder().Skip(1))
        {
            Assert.EndsWith("_comp", field.Name); Assert.EndsWith("Comp", field.MessageType.Name);
        }
        Assert.Empty(typeof(Player).GetEvents(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic));
        Assert.NotNull(typeof(PlayerLogicBase).GetMethod("OnPlayerEventType", BindingFlags.Instance | BindingFlags.NonPublic));
        Assert.Throws<InvalidOperationException>(() => player.Trigger(PlayerEventType.MainDataChanged));
        lock (player.SyncRoot)
        {
            player.Profile.Rename("Offline"); player.Wallet.Add(RewardKind.Hcoin, 0, 12);
            foreach (PlayerEventType type in Enum.GetValues<PlayerEventType>()) player.Trigger(type);
            player.Save();
        }
        using SqliteConnection connection = new($"Data Source={fixture.DatabasePath}"); connection.Open();
        using SqliteCommand command = connection.CreateCommand(); command.CommandText = "SELECT Data FROM Players WHERE Uid = $uid";
        command.Parameters.AddWithValue("$uid", player.Uid);
        PlayerSaveData stored = PlayerSaveData.Parser.ParseFrom(Assert.IsType<byte[]>(command.ExecuteScalar()));
        Assert.Equal("Offline", stored.Playerdata.Nickname); Assert.Equal(12, stored.WalletComp.Hcoin);
        Assert.Equal(player.SaveData, stored); Assert.Null(player.Session);
    }

    [Fact]
    public void QueryBuildersPreserveSelectionAndDoNotExposeMutableStorage()
    {
        Player player = CreatePlayer();
        lock (player.SyncRoot)
        {
            uint cardId = player.Inventory.Cards.First().Id;
            GetCardDataRsp cards = player.Inventory.CreateCardData(0, [cardId]);
            Assert.Equal(cardId, Assert.Single(cards.CardList).CardId); Assert.Equal(0u, cards.CardDataAll);
            cards.CardList[0].ExpLevel = 99;
            Assert.Equal(1u, player.Inventory.CreateCardData(0, [cardId]).CardList[0].ExpLevel);
            Assert.Empty(player.Inventory.CreateCardData(0, []).CardList);
            DeckItem deck = Assert.Single(player.Inventory.CreateDeckData(0, [1]).DeckItemList);
            Assert.Equal(player.Inventory.GetDeck(1).MainCards, deck.MainCardGroup.CardItems.Select(item => item.CardId));
            Assert.Equal(deck.MainCardGroup.CardItems.Count, deck.CardGroupCfg.CardItems.Count);
            uint coinId = player.Wallet.CoinIds.First(), ticketId = player.Wallet.TicketIds.First();
            Assert.Equal(coinId, Assert.Single(player.Wallet.CreateWalletData(0, [coinId]).WalletList).CoinId);
            Assert.Equal(ticketId, Assert.Single(player.Wallet.CreateTicketData(0, [ticketId]).TicketList).TicketId);
            uint materialId = GameTableCatalog.Instance.GetAllData<MaterialData>().First().Id;
            player.Inventory.Grant(RewardKind.Material, materialId, 5, sync: false);
            Assert.Equal(5, Assert.Single(player.Inventory.CreateMaterialData(0, [materialId]).MaterialList).MaterialNum);
            player.Story.Complete(1); Assert.Equal(1u, Assert.Single(player.Story.CreateStoryData(0, [1]).StoryList).StoryId);
            Assert.Empty(player.Story.CreateStoryData(0, [uint.MaxValue]).StoryList);
            LevelItem level = Assert.Single(player.Level.CreateLevelData(0, [1]).LevelList);
            Assert.Equal((uint)LevelStatus.UnderProgress, level.Status);
            player.Level.Begin(1); Assert.True(player.Level.Complete(1, sync: false));
            LevelItem completed = player.Level.CreateLevelData(0, [1]).LevelList[0];
            Assert.Equal((uint)LevelStatus.Done, completed.Status); Assert.Equal(1u, completed.Progress); Assert.Equal(0u, completed.Eval);
            LevelEndRsp end = player.Level.CreateLevelEnd(1, true, 1);
            Assert.Equal(40u, end.FirstPassRewardItem.ItemNum); Assert.Equal(player.Wallet.Hcoin, end.FirstPassRewardItem.CurItemNum);
            Assert.Null(player.Level.CreateLevelEnd(1, false, 1).FirstPassRewardItem);
            player.Save();
        }
    }

    [Fact]
    public async Task EveryDataEventUsesPlayerSendAndSyncFalseDoesNotPush()
    {
        Player player = CreatePlayer();
        using TcpListener listener = new(IPAddress.Loopback, 0); listener.Start();
        using TcpClient client = new(); await client.ConnectAsync((IPEndPoint)listener.LocalEndpoint);
        using TcpClient accepted = await listener.AcceptTcpClientAsync();
        GatewaySession session = new(accepted, new GatewayRouter(), new ServerOptions());
        using CancellationTokenSource timeout = new(TimeSpan.FromSeconds(15));
        Task running = session.RunAsync(timeout.Token);
        try
        {
            lock (player.SyncRoot)
            {
                session.Authenticate(player); session.Login();
                player.Profile.Rename("Online");
                uint card = GameTableCatalog.Instance.GetAllData<CardData>().First(row => !player.Inventory.OwnsCard(row.Id)).Id;
                player.Inventory.Grant(RewardKind.Card, card, 1);
                player.Inventory.ChangeDeck(1, "Changed", [card], []);
                uint material = GameTableCatalog.Instance.GetAllData<MaterialData>().First().Id;
                player.Inventory.Grant(RewardKind.Material, material, 5);
                player.Wallet.Add(RewardKind.Wallet, player.Wallet.CoinIds.First(), 1);
                player.Wallet.Add(RewardKind.Ticket, player.Wallet.TicketIds.First(), 1);
                player.Trigger(PlayerEventType.LevelsChanged);
                player.Profile.Rename("Silent", sync: false);
                player.Inventory.ChangeDeck(1, "Silent", [card], [], sync: false);
                player.Save();
                player.Send((ushort)Pbmisc.PingRsp.Types.CmdId.CmdId, new Pbmisc.PingRsp { Seq = 123 });
            }
            ushort[] expected =
            [
                (ushort)GetMainDataRsp.Types.CmdId.CmdId, (ushort)GetCardDataRsp.Types.CmdId.CmdId, (ushort)GetDeckDataRsp.Types.CmdId.CmdId,
                (ushort)GetMaterialDataRsp.Types.CmdId.CmdId, (ushort)GetWalletDataRsp.Types.CmdId.CmdId, (ushort)GetTicketDataRsp.Types.CmdId.CmdId,
                (ushort)GetLevelDataRsp.Types.CmdId.CmdId, (ushort)Pbmisc.PingRsp.Types.CmdId.CmdId,
            ];
            foreach (ushort command in expected)
            {
                NetPacket packet = await ReadPacketAsync(client.GetStream(), timeout.Token);
                Assert.Equal(command, packet.CmdId); Assert.Equal(0u, packet.Head.RpcId);
                Assert.Equal(0u, packet.Head.ClientSequenceId); Assert.Equal(player.Uid, packet.Head.UserId);
                if (command == (ushort)GetMainDataRsp.Types.CmdId.CmdId) Assert.Equal("Online", GetMainDataRsp.Parser.ParseFrom(packet.Body).Nickname);
                if (command == (ushort)GetDeckDataRsp.Types.CmdId.CmdId)
                    Assert.Equal("Changed", Assert.Single(GetDeckDataRsp.Parser.ParseFrom(packet.Body).DeckItemList).DeckName);
            }
        }
        finally { session.Close(); await running; }
        Assert.Null(player.Session);
    }

    [Fact]
    public async Task ReplacedSessionCannotReceiveOrUnsubscribeNewSessionNotifications()
    {
        Player player = CreatePlayer();
        using TcpListener listener = new(IPAddress.Loopback, 0); listener.Start();
        using TcpClient firstClient = new(); await firstClient.ConnectAsync((IPEndPoint)listener.LocalEndpoint);
        using TcpClient firstAccepted = await listener.AcceptTcpClientAsync();
        using TcpClient secondClient = new(); await secondClient.ConnectAsync((IPEndPoint)listener.LocalEndpoint);
        using TcpClient secondAccepted = await listener.AcceptTcpClientAsync();
        GatewaySession first = new(firstAccepted, new GatewayRouter(), new ServerOptions());
        GatewaySession second = new(secondAccepted, new GatewayRouter(), new ServerOptions());
        using CancellationTokenSource timeout = new(TimeSpan.FromSeconds(15));
        Task firstRunning = first.RunAsync(timeout.Token), secondRunning = second.RunAsync(timeout.Token);
        try
        {
            lock (player.SyncRoot)
            {
                first.Authenticate(player); first.Login(); second.Authenticate(player); second.Login();
                Assert.Throws<PlayerActionException>(() => second.Login());
            }
            await firstRunning;
            lock (player.SyncRoot)
            {
                Assert.Same(second, player.Session); player.Profile.Rename("Reconnected"); player.Save();
                player.Send((ushort)Pbmisc.PingRsp.Types.CmdId.CmdId, new Pbmisc.PingRsp { Seq = 456 });
            }
            NetPacket notification = await ReadPacketAsync(secondClient.GetStream(), timeout.Token);
            Assert.Equal((ushort)GetMainDataRsp.Types.CmdId.CmdId, notification.CmdId); Assert.Equal(0u, notification.Head.RpcId);
            Assert.Equal("Reconnected", GetMainDataRsp.Parser.ParseFrom(notification.Body).Nickname);
            NetPacket marker = await ReadPacketAsync(secondClient.GetStream(), timeout.Token);
            Assert.Equal((ushort)Pbmisc.PingRsp.Types.CmdId.CmdId, marker.CmdId); Assert.Equal(456u, Pbmisc.PingRsp.Parser.ParseFrom(marker.Body).Seq);
            Assert.True(first.IsClosed);
        }
        finally { first.Close(); second.Close(); await firstRunning; await secondRunning; }
        Assert.Null(player.Session);
    }

    [Fact]
    public async Task LevelResponsePrecedesSettledNotificationsAndDuplicateRequestDoesNotSettleAgain()
    {
        Player player = CreatePlayer();
        using TcpListener listener = new(IPAddress.Loopback, 0); listener.Start();
        using TcpClient client = new(); await client.ConnectAsync((IPEndPoint)listener.LocalEndpoint);
        using TcpClient accepted = await listener.AcceptTcpClientAsync();
        GatewaySession session = new(accepted, new GatewayRouter(), new ServerOptions());
        using CancellationTokenSource timeout = new(TimeSpan.FromSeconds(15));
        Task running = session.RunAsync(timeout.Token);
        try
        {
            lock (player.SyncRoot)
            {
                session.Authenticate(player); session.Login(); player.Level.Begin(1); player.Story.Complete(1); player.Save();
            }
            ushort command = (ushort)LevelEndReq.Types.CmdId.CmdId;
            byte[] request = new NetPacket(command, new LevelEndReq { LevelId = 1 }, new PacketHead { PacketId = command, RpcId = 1 }).Pack(65536);
            await client.GetStream().WriteAsync(request, timeout.Token);
            NetPacket response = await ReadPacketAsync(client.GetStream(), timeout.Token);
            Assert.Equal((ushort)LevelEndRsp.Types.CmdId.CmdId, response.CmdId); Assert.Equal(1u, response.Head.RpcId);
            Assert.Equal(40u, LevelEndRsp.Parser.ParseFrom(response.Body).FirstPassRewardItem.ItemNum);
            NetPacket profile = await ReadPacketAsync(client.GetStream(), timeout.Token);
            Assert.Equal((ushort)GetMainDataRsp.Types.CmdId.CmdId, profile.CmdId); Assert.Equal(0u, profile.Head.RpcId);
            Assert.Equal(40, GetMainDataRsp.Parser.ParseFrom(profile.Body).Hcoin);
            NetPacket levels = await ReadPacketAsync(client.GetStream(), timeout.Token);
            Assert.Equal((ushort)GetLevelDataRsp.Types.CmdId.CmdId, levels.CmdId); Assert.Equal(0u, levels.Head.RpcId);
            await client.GetStream().WriteAsync(request, timeout.Token);
            NetPacket duplicate = await ReadPacketAsync(client.GetStream(), timeout.Token);
            Assert.Equal((ushort)LevelEndRsp.Types.CmdId.CmdId, duplicate.CmdId); Assert.Equal(-2, LevelEndRsp.Parser.ParseFrom(duplicate.Body).Retcode);
            lock (player.SyncRoot)
            {
                Assert.Equal(1u, player.Level.PassCount(1)); Assert.Equal(40, player.Wallet.Hcoin);
                player.Send((ushort)Pbmisc.PingRsp.Types.CmdId.CmdId, new Pbmisc.PingRsp { Seq = 789 });
            }
            NetPacket marker = await ReadPacketAsync(client.GetStream(), timeout.Token);
            Assert.Equal((ushort)Pbmisc.PingRsp.Types.CmdId.CmdId, marker.CmdId);
        }
        finally { session.Close(); await running; }
    }

    private static async Task<NetPacket> ReadPacketAsync(Stream stream, CancellationToken cancellationToken)
    {
        byte[] prefix = new byte[NetPacket.PrefixSize]; await stream.ReadExactlyAsync(prefix, cancellationToken);
        int head = BinaryPrimitives.ReadUInt16BigEndian(prefix.AsSpan(4)); uint body = BinaryPrimitives.ReadUInt32BigEndian(prefix.AsSpan(6));
        byte[] frame = new byte[NetPacket.FixedSize + head + body]; prefix.CopyTo(frame, 0);
        await stream.ReadExactlyAsync(frame.AsMemory(NetPacket.PrefixSize), cancellationToken);
        NetPacket packet = new(); packet.UnPack(frame, 65536); return packet;
    }
}
