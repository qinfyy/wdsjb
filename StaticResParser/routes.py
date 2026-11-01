"""CN 6.1.0 配置文件到 protobuf 消息的路由。"""

from typing import Final


# 普通文件按 All{文件名}Datas 匹配；此表记录反汇编核实的读取入口。
ROOT_RVAS: Final[dict[str, int]] = {
    "ancient.bytes": 0x07416F08,  # CN 6.1.0 libil2cpp.so 0x07416F08
    "ancientgame.bytes": 0x06EBC430,  # CN 6.1.0 libil2cpp.so 0x06EBC430
    "anniversary2nd.bytes": 0x06F0007C,  # CN 6.1.0 libil2cpp.so 0x06F0007C
    "anniversary.bytes": 0x06F05DA0,  # CN 6.1.0 libil2cpp.so 0x06F05DA0
    "appraisal.bytes": 0x06C9ECCC,  # CN 6.1.0 libil2cpp.so 0x06C9ECCC
    "avatarPendants.bytes": 0x06CAB4A0,  # CN 6.1.0 libil2cpp.so 0x06CAB4A0
    "badge.bytes": 0x06CAC160,  # CN 6.1.0 libil2cpp.so 0x06CAC160
    "basenxx.bytes": 0x06CB1D78,  # CN 6.1.0 libil2cpp.so 0x06CB1D78
    "battle.bytes": 0x06AA4364,  # CN 6.1.0 libil2cpp.so 0x06AA4364
    "bighouse.bytes": 0x06AB6300,  # CN 6.1.0 libil2cpp.so 0x06AB6300
    "billing.bytes": 0x06AB9D18,  # CN 6.1.0 libil2cpp.so 0x06AB9D18
    "birthdayV3.bytes": 0x07255544,  # CN 6.1.0 libil2cpp.so 0x07255544
    "businesscard.bytes": 0x06DD3F14,  # CN 6.1.0 libil2cpp.so 0x06DD3F14
    "cafe.bytes": 0x06DD8A1C,  # CN 6.1.0 libil2cpp.so 0x06DD8A1C
    "card.bytes": 0x06D62138,  # CN 6.1.0 libil2cpp.so 0x06D62138
    "cardSort.bytes": 0x07262E18,  # CN 6.1.0 libil2cpp.so 0x07262E18
    "chapter.bytes": 0x07267CB4,  # CN 6.1.0 libil2cpp.so 0x07267CB4
    "character.bytes": 0x0726B608,  # CN 6.1.0 libil2cpp.so 0x0726B608
    "clickeffect.bytes": 0x07271108,  # CN 6.1.0 libil2cpp.so 0x07271108
    "clue.bytes": 0x07273380,  # CN 6.1.0 libil2cpp.so 0x07273380
    "coupleAppItem.bytes": 0x074B6D98,  # CN 6.1.0 libil2cpp.so 0x074B6D98
    "digitaldraw.bytes": 0x074E5920,  # CN 6.1.0 libil2cpp.so 0x074E5920
    "dlc.bytes": 0x06E855A0,  # CN 6.1.0 libil2cpp.so 0x06E855A0
    "doll.bytes": 0x06E8B64C,  # CN 6.1.0 libil2cpp.so 0x06E8B64C
    "download.bytes": 0x06D1ED60,  # CN 6.1.0 libil2cpp.so 0x06D1ED60
    "egypt.bytes": 0x06D21B04,  # CN 6.1.0 libil2cpp.so 0x06D21B04
    "event.bytes": 0x06C601FC,  # CN 6.1.0 libil2cpp.so 0x06C601FC
    "evidence.bytes": 0x06D9144C,  # CN 6.1.0 libil2cpp.so 0x06D9144C
    "explore.bytes": 0x06D9FE28,  # CN 6.1.0 libil2cpp.so 0x06D9FE28
    "functionopen.bytes": 0x06CB92B4,  # CN 6.1.0 libil2cpp.so 0x06CB92B4
    "gamebubble.bytes": 0x06CC16EC,  # CN 6.1.0 libil2cpp.so 0x06CC16EC
    "gamepaint.bytes": 0x06CC5DC8,  # CN 6.1.0 libil2cpp.so 0x06CC5DC8
    "gamepoker.bytes": 0x06CC8E94,  # CN 6.1.0 libil2cpp.so 0x06CC8E94
    "gamequiz.bytes": 0x06CCA4E4,  # CN 6.1.0 libil2cpp.so 0x06CCA4E4
    "garden.bytes": 0x06F2E064,  # CN 6.1.0 libil2cpp.so 0x06F2E064
    "generalactivity.bytes": 0x06F3FEFC,  # CN 6.1.0 libil2cpp.so 0x06F3FEFC
    "getgift.bytes": 0x07013304,  # CN 6.1.0 libil2cpp.so 0x07013304
    "guide.bytes": 0x07021CB8,  # CN 6.1.0 libil2cpp.so 0x07021CB8
    "hcexchange.bytes": 0x0702AEE4,  # CN 6.1.0 libil2cpp.so 0x0702AEE4
    "homeland.bytes": 0x0733A4E0,  # CN 6.1.0 libil2cpp.so 0x0733A4E0
    "iceland.bytes": 0x0702F1A8,  # CN 6.1.0 libil2cpp.so 0x0702F1A8
    "initpackage.bytes": 0x070431D8,  # CN 6.1.0 libil2cpp.so 0x070431D8
    "inquiry.bytes": 0x07045190,  # CN 6.1.0 libil2cpp.so 0x07045190
    "interactive.bytes": 0x06E48CD8,  # CN 6.1.0 libil2cpp.so 0x06E48CD8
    "inves.bytes": 0x06E4F7D8,  # CN 6.1.0 libil2cpp.so 0x06E4F7D8
    "investigation.bytes": 0x06E56D1C,  # CN 6.1.0 libil2cpp.so 0x06E56D1C
    "invitation.bytes": 0x06E350FC,  # CN 6.1.0 libil2cpp.so 0x06E350FC
    "island.bytes": 0x06E38470,  # CN 6.1.0 libil2cpp.so 0x06E38470
    "item.bytes": 0x0687E734,  # CN 6.1.0 libil2cpp.so 0x0687E734
    "kitchen.bytes": 0x06883934,  # CN 6.1.0 libil2cpp.so 0x06883934
    "level.bytes": 0x0688F2FC,  # CN 6.1.0 libil2cpp.so 0x0688F2FC
    "live2d.bytes": 0x0747E200,  # CN 6.1.0 libil2cpp.so 0x0747E200
    "longtimecard.bytes": 0x06E6B08C,  # CN 6.1.0 libil2cpp.so 0x06E6B08C
    "mainlineCountdown.bytes": 0x06E6F12C,  # CN 6.1.0 libil2cpp.so 0x06E6F12C
    "match.bytes": 0x06E75A28,  # CN 6.1.0 libil2cpp.so 0x06E75A28
    "minigame.bytes": 0x06FB3330,  # CN 6.1.0 libil2cpp.so 0x06FB3330
    "miscgoto.bytes": 0x06FB9650,  # CN 6.1.0 libil2cpp.so 0x06FB9650
    "month.bytes": 0x0727A60C,  # CN 6.1.0 libil2cpp.so 0x0727A60C
    "negotiation.bytes": 0x0727DED4,  # CN 6.1.0 libil2cpp.so 0x0727DED4
    "newbie.bytes": 0x0728BE68,  # CN 6.1.0 libil2cpp.so 0x0728BE68
    "newMessage.bytes": 0x0728E6BC,  # CN 6.1.0 libil2cpp.so 0x0728E6BC
    "notification.bytes": 0x0729100C,  # CN 6.1.0 libil2cpp.so 0x0729100C
    "observe.bytes": 0x07155BC8,  # CN 6.1.0 libil2cpp.so 0x07155BC8
    "oldPlayerReturn.bytes": 0x07160D84,  # CN 6.1.0 libil2cpp.so 0x07160D84
    "osdata.bytes": 0x06710268,  # CN 6.1.0 libil2cpp.so 0x06710268
    "packageRelation.bytes": 0x06716040,  # CN 6.1.0 libil2cpp.so 0x06716040
    "parable.bytes": 0x0671C550,  # CN 6.1.0 libil2cpp.so 0x0671C550
    "personal.bytes": 0x0672A1FC,  # CN 6.1.0 libil2cpp.so 0x0672A1FC
    "pet.bytes": 0x06EA66E8,  # CN 6.1.0 libil2cpp.so 0x06EA66E8
    "phone.bytes": 0x07084610,  # CN 6.1.0 libil2cpp.so 0x07084610
    "photo.bytes": 0x070997C0,  # CN 6.1.0 libil2cpp.so 0x070997C0
    "playerbirthday.bytes": 0x0709CFBC,  # CN 6.1.0 libil2cpp.so 0x0709CFBC
    "polaroid.bytes": 0x03788B64,  # CN 6.1.0 libil2cpp.so 0x03788B64
    "postcard.bytes": 0x0378C4A0,  # CN 6.1.0 libil2cpp.so 0x0378C4A0
    "profession.bytes": 0x0379983C,  # CN 6.1.0 libil2cpp.so 0x0379983C
    "railcruise.bytes": 0x071A9010,  # CN 6.1.0 libil2cpp.so 0x071A9010
    "reputation.bytes": 0x06FEBE04,  # CN 6.1.0 libil2cpp.so 0x06FEBE04
    "richman.bytes": 0x06CF8F88,  # CN 6.1.0 libil2cpp.so 0x06CF8F88
    "role.bytes": 0x06FFAF50,  # CN 6.1.0 libil2cpp.so 0x06FFAF50
    "rpgminigame.bytes": 0x07002888,  # CN 6.1.0 libil2cpp.so 0x07002888
    "scrabble.bytes": 0x070080AC,  # CN 6.1.0 libil2cpp.so 0x070080AC
    "search2D.bytes": 0x0731CB60,  # CN 6.1.0 libil2cpp.so 0x0731CB60
    "setting.bytes": 0x07321988,  # CN 6.1.0 libil2cpp.so 0x07321988
    "shop.bytes": 0x07325B50,  # CN 6.1.0 libil2cpp.so 0x07325B50
    "sound.bytes": 0x07331F14,  # CN 6.1.0 libil2cpp.so 0x07331F14
    "sourcepath.bytes": 0x073348D8,  # CN 6.1.0 libil2cpp.so 0x073348D8
    "splash.bytes": 0x071B292C,  # CN 6.1.0 libil2cpp.so 0x071B292C
    "story.bytes": 0x071B5CE0,  # CN 6.1.0 libil2cpp.so 0x071B5CE0
    "task.bytes": 0x06D78050,  # CN 6.1.0 libil2cpp.so 0x06D78050
    "tbrpg.bytes": 0x06D7D834,  # CN 6.1.0 libil2cpp.so 0x06D7D834
    "tbrpgmap.bytes": 0x06D86010,  # CN 6.1.0 libil2cpp.so 0x06D86010
    "temporary.bytes": 0x06D86D18,  # CN 6.1.0 libil2cpp.so 0x06D86D18
    "text.bytes": 0x0722A32C,  # CN 6.1.0 libil2cpp.so 0x0722A32C
    "timelineShow.bytes": 0x0723AC1C,  # CN 6.1.0 libil2cpp.so 0x0723AC1C
    "tower.bytes": 0x0723CBAC,  # CN 6.1.0 libil2cpp.so 0x0723CBAC
    "train.bytes": 0x069BB820,  # CN 6.1.0 libil2cpp.so 0x069BB820
    "translationcn.bytes": 0x0699A428,  # CN 6.1.0 libil2cpp.so 0x0699A428
    "translationen.bytes": 0x069A22D8,  # CN 6.1.0 libil2cpp.so 0x069A22D8
    "translationjp.bytes": 0x069AA188,  # CN 6.1.0 libil2cpp.so 0x069AA188
    "translationkr.bytes": 0x069B2038,  # CN 6.1.0 libil2cpp.so 0x069B2038
    "translationtw.bytes": 0x06B364C0,  # CN 6.1.0 libil2cpp.so 0x06B364C0
    "urbanlegend.bytes": 0x06C4D884,  # CN 6.1.0 libil2cpp.so 0x06C4D884
    "vip.bytes": 0x071D45D8,  # CN 6.1.0 libil2cpp.so 0x071D45D8
    "wallet.bytes": 0x071D7D10,  # CN 6.1.0 libil2cpp.so 0x071D7D10
    "weakguide.bytes": 0x071DB218,  # CN 6.1.0 libil2cpp.so 0x071DB218
    "whisper.bytes": 0x071DBEF8,  # CN 6.1.0 libil2cpp.so 0x071DBEF8
    "wiki.bytes": 0x071E2970,  # CN 6.1.0 libil2cpp.so 0x071E2970
}


SPLIT_MESSAGES: Final[dict[str, str]] = {
    "story": "StoryInfoConfigure",  # CN 6.1.0 libil2cpp.so 0x071BA07C
    "explore": "ExploreMapDataConfigure",  # CN 6.1.0 libil2cpp.so 0x06DA6AC0
    "text": "TextMapGroupConfigure",  # CN 6.1.0 libil2cpp.so 0x0722BCD8
    "live2d": "Live2DStoryGroupConfigure",  # CN 6.1.0 libil2cpp.so 0x0747E7A4
}

