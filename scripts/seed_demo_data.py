import asyncio
import os
import pathlib
import sys
from dataclasses import dataclass
from typing import Dict, List

import asyncpg

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from app.db.errors import EntityDoesNotExist
from app.db.repositories.articles import ArticlesRepository
from app.db.repositories.comments import CommentsRepository
from app.db.repositories.governance import GovernanceRepository
from app.db.repositories.users import UsersRepository
from app.models.schemas.articles import ArticleAIAnalysis
from app.models.schemas.comments import CommentModeration


@dataclass(frozen=True)
class ArticleSeed:
    slug: str
    title: str
    description: str
    body: str
    tags: List[str]
    content_status: str = "visible"
    review_status: str = "approved"
    score: int = 82
    summary: str = ""
    risk_labels: List[str] = None
    suggestions: List[str] = None


@dataclass(frozen=True)
class CommentSeed:
    article_slug: str
    username: str
    body: str
    content_status: str = "visible"
    review_status: str = "approved"
    severity: str = "low"
    reason: str = "Discussion is constructive."
    suggested_revision: str = ""
    note: str = ""


USERS = [
    {"username": "admin", "email": "admin@example.com", "password": "password"},
    {"username": "lena", "email": "lena@conduit.local", "password": "password"},
    {"username": "marcus", "email": "marcus@conduit.local", "password": "password"},
    {"username": "yara", "email": "yara@conduit.local", "password": "password"},
    {"username": "owen", "email": "owen@conduit.local", "password": "password"},
    {"username": "qiao", "email": "qiao@conduit.local", "password": "password"},
    {"username": "ming", "email": "ming@conduit.local", "password": "password"},
    {"username": "siyan", "email": "siyan@conduit.local", "password": "password"},
]

ARTICLES = [
    ArticleSeed(
        slug="jiangnan-night-market-guide",
        title="本地人写给第一次来的江南夜市指南",
        description="从几点到最好逛、先吃什么、哪几档最容易排队，这一篇都给你讲清楚。",
        body=(
            "很多第一次来江南夜市的人，会在七点半以后才慢慢进场，结果第一轮最好的摊位已经开始排长队。"
            "如果你想吃得舒服一点，最适合的时间其实是傍晚六点二十到七点之间。这个时段炭火刚稳定，摊主还"
            "有余裕和熟客聊天，煎台和烤网也是一天里最干净的时候。\n\n"
            "我通常会从东侧入口那家烤鱿鱼开始，接着往茶铺方向走。沿途不要急着买太多，夜市真正值得逛的"
            "是第二轮加推的小份菜单。九点后有一家锅贴会换成虾仁韭黄馅，靠近旧码头办公室的那家烘焙摊会"
            "出炉芝麻千层面包，带回去第二天早上配咖啡很好。想找座位的话，不要坐在水边，看起来热闹，实"
            "际上风大又吵。旧渡口墙边那排条纹雨棚下的位置才最稳。"
        ),
        tags=["城市漫游", "夜市", "美食"],
        summary="一篇实用度很高的夜市攻略，重点在于节奏、路线和摊位选择。",
    ),
    ArticleSeed(
        slug="small-team-retrospective-rhythm",
        title="小团队怎么把复盘会开得不空不散",
        description="不是做情绪发泄，也不是写会议纪要，这是一套够轻但能真落地的复盘方法。",
        body=(
            "我见过很多复盘会一开始都很认真，最后却变成两种极端：要么大家把它开成了吐槽大会，要么又"
            "因为怕尴尬，只剩下一些谁都不会反对的空话。真正有用的复盘，会很具体，而且一定要跟下一个"
            "迭代里能执行的动作绑在一起。\n\n"
            "我们现在的做法很简单，先列事件，再谈感受。比如某次版本发布延迟，不先说谁压力大，而是先"
            "把时间线摊开：文案什么时候晚了半天、迁移脚本为什么没人复核、客服队列为什么空了一整天。"
            "当事实顺序摆出来以后，团队讨论情绪反而更坦诚，因为所有人都知道自己在回应什么。\n\n"
            "第二个关键动作，是要求每条抱怨后面必须跟一个实验。不是宣誓，不是反省，而是一个能在下一"
            "周试起来的小动作。这样复盘会才不会奖励那些声音最大、但没有后续的人。"
        ),
        tags=["产品团队", "协作", "流程"],
        summary="强调时间线、可执行实验和短反馈回路的小团队复盘方法。",
    ),
    ArticleSeed(
        slug="balcony-herb-garden-notes",
        title="一个朝西阳台种香草一整季后的实际笔记",
        description="什么能活，什么会蔫，为什么书上那些建议搬到真实阳台里会失效。",
        body=(
            "春天刚开始的时候，我以为罗勒会是最好养的那盆，结果六月一到就开始萎。反而是百里香和迷迭"
            "香，在裂了角的陶盆里长得很稳定，像是天生就适合被忽视。这个朝西阳台的问题其实不只是晒，"
            "而是楼间风道带来的持续干燥。轻一点的盆很快就干，叶面大的植物还没被晒伤，先被风吹得发卷。"
            "\n\n"
            "后来我把盆栽的摆法从“按菜谱需求”改成“按喝水习惯”分组，状态才开始稳定。薄荷和欧芹放在"
            "深盆里靠里侧，迷迭香和百里香扔到最热的角落，莳萝补种了两轮还是不情不愿。很多园艺建议在书"
            "里看着都对，但阳台这种小环境，一定是先观察，再谈方法。"
        ),
        tags=["园艺", "居家", "生活观察"],
        summary="一篇关于真实阳台环境、风向和浇水节奏的香草种植笔记。",
    ),
    ArticleSeed(
        slug="museum-audio-guide-notes",
        title="为什么好的展览导览音频一定要留白",
        description="不是讲得越多越专业，真正舒服的导览，往往是知道什么时候该停下来。",
        body=(
            "很多博物馆的导览音频有一个共同问题：它们太想把所有信息都一次讲完。结果不是更清楚，而是更"
            "累。观众还没来得及看完眼前这件作品，耳机里的说明已经讲到了下一段历史背景，整个人会被推着"
            "走。\n\n"
            "好的导览音频，不应该和空间抢注意力。它要给脚步声、回音、停顿和观众自己的判断留位置。每"
            "一段音频只回答一个问题就够了，比如“这件作品最值得看哪一处细节”，或者“为什么它会放在这个"
            "展厅”。如果一个房间本身信息已经很多，导览系统最好的选择反而可能是克制。留白不是偷懒，而"
            "是体验设计的一部分。"
        ),
        tags=["设计", "展览", "文化观察"],
        summary="讨论导览音频密度、节奏和空间感的一篇体验设计文章。",
    ),
    ArticleSeed(
        slug="river-cleanup-field-log",
        title="一次周末河道清理之后，我们真正看见了什么",
        description="捡垃圾只是最表层的工作，更多线索藏在重复出现的抛弃物和水流方向里。",
        body=(
            "很多人提到河道垃圾，脑子里想到的都是塑料瓶和外卖袋，但我们那天真正捡得最多的，其实是装修"
            "碎料和一碰就裂的泡沫包装。前一个小时大家都在快速装袋，真正更重要的工作，反而发生在节奏慢"
            "下来的时候：把重复出现的垃圾类型分开、记录几处明显的偷倒点、标出几条暴雨后会直接冲进芦苇"
            "带的排水口。\n\n"
            "清理活动的好处在于它可见，参加完会让人觉得至少做成了一件事。但如果没有后续，它也很容易"
            "变成一种让人安心的惯例。我们最后带走的不只是干净一点的步道，还有坐标、照片，以及几家需要"
            "继续盯着的商户名单。"
        ),
        tags=["社区行动", "环保", "田野记录"],
        summary="把志愿清理和上游治理联系起来的一篇现场记录。",
    ),
    ArticleSeed(
        slug="late-subway-essay-draft",
        title="末班地铁里那些短暂又亲密的片刻",
        description="一篇还在打磨中的随笔，写晚归通勤、车窗反光和那些没有说完的话。",
        body=(
            "每座城市在晚上十点半之后，都会长出一个白天看不见的版本。末班地铁上的对话，常常一半像交代，"
            "一半像盘点。有人对着手机默默算今天的开销，有人已经把一通难打的电话在心里排练了很多遍。站间"
            "灯光一暗，车窗就变成镜子，镜子里那些疲惫又克制的脸，比白天低头赶路时更诚实一点。\n\n"
            "这篇随笔现在的问题，是情绪有了，具体场景却还不够。它需要更多站点、更多动作、更多听见一半"
            "的话，而不是一再强调夜晚会让人变得坦白。真正能撑住这篇文章的，应该是细节，不是判断。"
        ),
        tags=["随笔", "城市生活", "写作"],
        content_status="pending",
        review_status="pending",
        score=61,
        summary="文章有氛围，但细节支点不够，需要补充更具体的场景和动作。",
        suggestions=[
            "补出几个具体站点和场景节点。",
            "减少重复的抽象抒情表达。",
            "让一个被听见的片段承担主要情绪。",
        ],
    ),
    ArticleSeed(
        slug="unsupported-health-routine-thread",
        title="一套据说一夜见效的健康作息法",
        description="内容混杂论坛传闻和未经证实的建议，当前版本不适合公开展示。",
        body=(
            "这篇草稿把许多论坛传闻拼在了一起：热毛巾、冰刺激、多种粉末补充剂、深夜高强度训练，还有一整"
            "套没有说明剂量的组合服用建议。文字里充满了“很多人都说有效”“不舒服说明在起作用”这一类表达，"
            "但几乎没有可靠来源。\n\n"
            "它里面不是完全没有值得讨论的部分，像固定睡眠时间、减少晚间社交媒体这些方向都可以展开。但"
            "现在这版最大的问题，是把流言写成了教程，甚至暗示不适感本身就是效果证明，这样的内容不该直接"
            "公开。"
        ),
        tags=["健康", "网络观察", "草稿"],
        content_status="hidden",
        review_status="rejected",
        score=34,
        summary="内容包含高风险、弱证据的健康建议，当前版本不适合公开发布。",
        risk_labels=["健康误导", "高风险建议"],
        suggestions=[
            "删除没有证据支持的指导性语句。",
            "把论坛经验替换为可核查的公共健康资料。",
            "不要把不适反应写成有效证明。",
        ],
    ),
    ArticleSeed(
        slug="weekday-breakfast-walks",
        title="连续一个月早起散步后，我的工作日早晨变了什么",
        description="不是鸡血式自律，而是一种让大脑慢一点进入工作状态的方式。",
        body=(
            "我原本以为早起散步的好处会体现在体能上，后来发现最明显的变化反而是注意力。以前我起床后会"
            "直接坐到电脑前，整个人虽然已经打开文档，但思路像是还堵在睡眠和消息提醒之间。后来改成出门"
            "走二十五分钟，再回来吃早餐，工作日的开头稳定很多。\n\n"
            "这件事最关键的不是步数，也不是速度，而是顺序。先让身体进入白天，再让任务进入脑子。沿路"
            "看早餐店出摊、便利店补货、校门口开始拥挤，这种缓慢的现实感会把人从屏幕里拉出来。它不是什"
            "么效率神话，但确实让我的上午更像一个开始，而不是一个被提醒推着走的延续。"
        ),
        tags=["生活方式", "晨间", "专注"],
        summary="一篇关于晨间散步如何改善工作节奏和注意力状态的生活观察。",
    ),
    ArticleSeed(
        slug="community-library-redesign",
        title="社区图书角改造之后，真正增加的不是借阅量",
        description="把空间重新整理后，变化最大的反而是人停下来的时间和交流方式。",
        body=(
            "社区图书角原来最大的问题不是书少，而是没有停留感。书架靠墙排开，中间只放了几把塑料椅子，"
            "人路过会看一眼，但很少真的坐下来。我们这次改造最先动的，不是书目，而是动线：把入口那排"
            "架子转成斜角，留出一块能让人站定翻阅的缓冲区，再把儿童区和成人区之间那面空白墙换成展示板。"
            "\n\n"
            "改完以后，借阅量当然也有上升，但更明显的是停留时间。有人会在下班后坐十五分钟翻一本摄影集，"
            "家长开始愿意在儿童区旁边等孩子自己挑书，两个原本互不相识的老人会因为一本地方志聊起来。一个"
            "空间是不是公共的，很多时候不看它摆了什么，而看它是否让人愿意多留一会儿。"
        ),
        tags=["社区", "空间设计", "阅读"],
        summary="围绕公共空间停留感、动线和小型社区图书角改造的案例文章。",
    ),
    ArticleSeed(
        slug="weekend-ceramics-class-journal",
        title="第一次去周末陶艺课，我学到的不是拉坯",
        description="比技巧更难的是接受作品一开始总会很难看这件事。",
        body=(
            "很多人去上手工课，都是带着“最好马上做出一个像样成品”的期待去的，我也一样。可第一节陶艺课"
            "上，老师几乎没有花很多时间讲美感，而是在反复强调手的位置、呼吸的节奏和失败会非常正常。轮盘"
            "一转起来，任何一点急躁都会立刻出现在泥壁上。\n\n"
            "后来我意识到，那天最重要的收获不是技术，而是重新认识“慢下来”这件事。你不能一边想着成品，"
            "一边把手稳稳地放在泥上。必须先接受眼前这一团东西现在还不成形，然后才有可能让它慢慢变好。这"
            "种状态在很多工作里都罕见，因为我们太习惯用结果倒逼过程。"
        ),
        tags=["手作", "课程体验", "慢生活"],
        summary="一篇关于陶艺初学体验、节奏感和过程容忍度的课堂笔记。",
    ),
    ArticleSeed(
        slug="old-town-breakfast-map",
        title="老城区早餐地图：五家不需要特意打卡却很值得去的店",
        description="不追网红，不抢第一口，只是认真整理那些能让早晨变好的小店。",
        body=(
            "早餐店最怕被讲成排行榜。真正会反复去吃的店，未必是最好拍、最出名、最适合外地游客一早冲去"
            "排队的那种。它们往往是你在赶着去上班、或者只是想安静吃完一顿热乎饭的时候，会自然拐进去的"
            "地方。\n\n"
            "这份地图里我最喜欢的是桥边那家豆腐汤店。老板不太爱讲话，但汤底稳，油条总是炸得偏干一点，"
            "正好适合浸一下再吃。还有巷子深处那家做苏式面的小馆，早上只卖两种浇头，卖完就收。你很难把"
            "这些地方讲得多传奇，可一座城市的早晨，本来就不需要传奇，它需要的是可靠。"
        ),
        tags=["城市漫游", "早餐", "本地小店"],
        summary="不追网红路线、强调可靠和日常回访价值的早餐地图。",
    ),
    ArticleSeed(
        slug="freelance-invoice-notes",
        title="自由职业第二年，我终于把报价和开票这件事理顺了",
        description="不是多复杂的财务知识，而是把流程写清楚之后，整个人轻松了很多。",
        body=(
            "自由职业第一年最消耗我的，常常不是工作本身，而是报价、合同、开票、催款这些零散又必须认真"
            "对待的流程。项目一多，脑子里就会有一种永远还有几件没收尾的感觉。后来我花了一周，把常用模"
            "板、报价区间、付款节点和发票备注全整理出来，事情突然顺了很多。\n\n"
            "我现在最坚持的一个原则，是把付款条件前置写清楚，不在项目做到一半时才讨论。另一个变化，是"
            "每个报价单后面都附一段“本次合作默认包含什么，不包含什么”的说明。很多摩擦并不是客户故意压"
            "价，而是双方对边界想象不同。你越早把边界写出来，后面就越像合作，而不是猜测。"
        ),
        tags=["自由职业", "工作方法", "财务流程"],
        summary="围绕报价、开票和合作边界整理出的自由职业工作方法。",
    ),
]

COMMENTS = [
    CommentSeed(
        article_slug="jiangnan-night-market-guide",
        username="marcus",
        body="你提到的芝麻千层面包我也很喜欢，九点后那一炉真的比前面几轮状态更好。",
    ),
    CommentSeed(
        article_slug="jiangnan-night-market-guide",
        username="yara",
        body="旧渡口旁边那家焙茶我也推荐，尤其适合吃完油炸的东西之后缓一下口。",
    ),
    CommentSeed(
        article_slug="small-team-retrospective-rhythm",
        username="owen",
        body="把抱怨强制改成实验这个动作很有用，我们团队这么做后复盘会明显不再空转。",
    ),
    CommentSeed(
        article_slug="museum-audio-guide-notes",
        username="lena",
        body="留白也是设计这一点说得很好，很多展览导览的问题就是太怕观众听不懂，于是讲得太满。",
    ),
    CommentSeed(
        article_slug="river-cleanup-field-log",
        username="marcus",
        body="我们上个月做河道巡查时也发现了类似的泡沫包装堆点，做重复点位记录真的很必要。",
    ),
    CommentSeed(
        article_slug="late-subway-essay-draft",
        username="owen",
        body="这篇的气氛已经有了，但现在确实有点一直围着同一种情绪打转，细节再多一点会更稳。",
        content_status="pending",
        review_status="pending",
        severity="medium",
        reason="观点本身没有问题，但语气和表达方式需要人工复核。",
        suggested_revision="保留批评意见，但把判断写得更具体一些。",
    ),
    CommentSeed(
        article_slug="museum-audio-guide-notes",
        username="yara",
        body="这篇文章写得太端着了，像是根本没在现场真正观察过观众怎么走动。",
        content_status="hidden",
        review_status="rejected",
        severity="high",
        reason="评论表达带有明显攻击性，不适合直接公开显示。",
        suggested_revision="保留观点，但删除针对作者能力的攻击性表达。",
        note="攻击性表述过强，管理员驳回。",
    ),
    CommentSeed(
        article_slug="weekday-breakfast-walks",
        username="qiao",
        body="我也试过先散步再开始工作，最明显的变化是上午开会时不那么浮躁了。",
    ),
    CommentSeed(
        article_slug="weekday-breakfast-walks",
        username="ming",
        body="你说的不是效率神话而是顺序感，我很认同，很多早晨的问题其实是切换太急。",
    ),
    CommentSeed(
        article_slug="community-library-redesign",
        username="siyan",
        body="“停留感”这个词很准确，我们社区活动室也是重新调整座位以后，交流才真正多起来。",
    ),
    CommentSeed(
        article_slug="weekend-ceramics-class-journal",
        username="lena",
        body="接受一开始会很难看这件事，几乎适用于所有手工课，也适用于很多创作型工作。",
    ),
    CommentSeed(
        article_slug="old-town-breakfast-map",
        username="owen",
        body="早餐不需要传奇，它需要可靠，这句话很妙，很多好店就是靠这个留住人的。",
    ),
    CommentSeed(
        article_slug="freelance-invoice-notes",
        username="qiao",
        body="把合作边界写进报价单这点特别实用，我以前总觉得这样会太强硬，后来发现恰恰会让合作更轻松。",
    ),
    CommentSeed(
        article_slug="community-library-redesign",
        username="ming",
        body="如果能再写一点儿童区和成人区如何互不打扰就更好了，这部分很有参考价值。",
    ),
    CommentSeed(
        article_slug="old-town-breakfast-map",
        username="siyan",
        body="桥边豆腐汤那家我知道，确实不是打卡型店，但会让人想再去。",
    ),
]

ARTICLE_FAVORITES = [
    ("jiangnan-night-market-guide", "marcus"),
    ("jiangnan-night-market-guide", "qiao"),
    ("small-team-retrospective-rhythm", "owen"),
    ("community-library-redesign", "lena"),
    ("weekday-breakfast-walks", "siyan"),
]

COMMENT_LIKES = [
    ("你提到的芝麻千层面包我也很喜欢，九点后那一炉真的比前面几轮状态更好。", "lena"),
    ("你提到的芝麻千层面包我也很喜欢，九点后那一炉真的比前面几轮状态更好。", "qiao"),
    ("把抱怨强制改成实验这个动作很有用，我们团队这么做后复盘会明显不再空转。", "lena"),
    ("把抱怨强制改成实验这个动作很有用，我们团队这么做后复盘会明显不再空转。", "ming"),
    ("我也试过先散步再开始工作，最明显的变化是上午开会时不那么浮躁了。", "siyan"),
    ("我也试过先散步再开始工作，最明显的变化是上午开会时不那么浮躁了。", "owen"),
    ("我也试过先散步再开始工作，最明显的变化是上午开会时不那么浮躁了。", "marcus"),
]


def article_analysis(seed: ArticleSeed) -> ArticleAIAnalysis:
    return ArticleAIAnalysis(
        summary=seed.summary or seed.description,
        recommendedTagList=seed.tags[:4],
        reading_time_minutes=max(1, len(seed.body.split()) // 180),
        content_score=seed.score,
        riskLabels=seed.risk_labels or [],
        suggestions=seed.suggestions
        or [
            "Keep the opening concrete and specific.",
            "Tighten transitions between sections.",
            "Preserve the strongest observational detail.",
        ],
        model="demo-editorial-review",
    )


def comment_analysis(seed: CommentSeed) -> CommentModeration:
    return CommentModeration(
        allowed=seed.review_status != "rejected",
        category="discussion",
        severity=seed.severity,
        reason=seed.reason,
        suggestedRevision=seed.suggested_revision,
        confidence=0.88 if seed.review_status == "approved" else 0.73,
        model="demo-comment-review",
    )


async def purge_existing_demo_data(conn: asyncpg.Connection) -> None:
    await conn.execute(
        """
        DELETE FROM article_embeddings
        WHERE article_id IN (
            SELECT id
            FROM articles
            WHERE slug = ANY($1::text[])
               OR author_id IN (
                    SELECT id
                    FROM users
                    WHERE email LIKE '%@conduit.local'
               )
        )
        """,
        [item.slug for item in ARTICLES],
    )
    await conn.execute(
        """
        DELETE FROM user_notifications
        WHERE user_id IN (
            SELECT id
            FROM users
            WHERE email LIKE '%@conduit.local'
               OR email = 'admin@example.com'
        )
        """
    )
    await conn.execute(
        """
        DELETE FROM content_audit_logs
        WHERE actor_id IN (
            SELECT id
            FROM users
            WHERE email LIKE '%@conduit.local'
               OR email = 'admin@example.com'
        )
           OR article_id IN (
            SELECT id
            FROM articles
            WHERE slug = ANY($1::text[])
               OR author_id IN (
                    SELECT id
                    FROM users
                    WHERE email LIKE '%@conduit.local'
               )
        )
           OR comment_id IN (
            SELECT id
            FROM commentaries
            WHERE article_id IN (
                SELECT id
                FROM articles
                WHERE slug = ANY($1::text[])
                   OR author_id IN (
                        SELECT id
                        FROM users
                        WHERE email LIKE '%@conduit.local'
                   )
            )
        )
        """,
        [item.slug for item in ARTICLES],
    )
    await conn.execute(
        """
        DELETE FROM content_reports
        WHERE article_id IN (
            SELECT id
            FROM articles
            WHERE slug = ANY($1::text[])
               OR author_id IN (
                    SELECT id
                    FROM users
                    WHERE email LIKE '%@conduit.local'
               )
        )
           OR comment_id IN (
            SELECT id
            FROM commentaries
            WHERE article_id IN (
                SELECT id
                FROM articles
                WHERE slug = ANY($1::text[])
                   OR author_id IN (
                        SELECT id
                        FROM users
                        WHERE email LIKE '%@conduit.local'
                   )
            )
        )
        """,
        [item.slug for item in ARTICLES],
    )
    await conn.execute(
        """
        DELETE FROM article_moderation_logs
        WHERE article_id IN (
            SELECT id
            FROM articles
            WHERE slug = ANY($1::text[])
               OR author_id IN (
                    SELECT id
                    FROM users
                    WHERE email LIKE '%@conduit.local'
               )
        )
        """,
        [item.slug for item in ARTICLES],
    )
    await conn.execute(
        """
        DELETE FROM comment_moderation_logs
        WHERE article_id IN (
            SELECT id
            FROM articles
            WHERE slug = ANY($1::text[])
               OR author_id IN (
                    SELECT id
                    FROM users
                    WHERE email LIKE '%@conduit.local'
               )
        )
        """,
        [item.slug for item in ARTICLES],
    )
    await conn.execute(
        """
        DELETE FROM commentaries
        WHERE article_id IN (
            SELECT id
            FROM articles
            WHERE slug = ANY($1::text[])
               OR author_id IN (
                    SELECT id
                    FROM users
                    WHERE email LIKE '%@conduit.local'
               )
        )
        """,
        [item.slug for item in ARTICLES],
    )
    await conn.execute(
        """
        DELETE FROM favorites
        WHERE article_id IN (
            SELECT id
            FROM articles
            WHERE slug = ANY($1::text[])
               OR author_id IN (
                    SELECT id
                    FROM users
                    WHERE email LIKE '%@conduit.local'
               )
        )
        """,
        [item.slug for item in ARTICLES],
    )
    await conn.execute(
        """
        DELETE FROM articles_to_tags
        WHERE article_id IN (
            SELECT id
            FROM articles
            WHERE slug = ANY($1::text[])
               OR author_id IN (
                    SELECT id
                    FROM users
                    WHERE email LIKE '%@conduit.local'
               )
        )
        """,
        [item.slug for item in ARTICLES],
    )
    await conn.execute(
        """
        DELETE FROM articles
        WHERE slug = ANY($1::text[])
           OR author_id IN (
                SELECT id
                FROM users
                WHERE email LIKE '%@conduit.local'
           )
        """,
        [item.slug for item in ARTICLES],
    )
    await conn.execute(
        """
        DELETE FROM users
        WHERE email LIKE '%@conduit.local'
        """
    )


async def seed_users(users_repo: UsersRepository):
    users: Dict[str, object] = {}
    for item in USERS:
        try:
            existing = await users_repo.get_user_by_email(email=item["email"])
            await users_repo.update_user(
                user=existing,
                username=item["username"],
                email=item["email"],
                password=item["password"],
            )
        except EntityDoesNotExist:
            await users_repo.create_user(**item)
        users[item["username"]] = await users_repo.get_user_by_username(
            username=item["username"],
        )
    return users


async def seed_articles(articles_repo: ArticlesRepository, users):
    seeded = {}
    article_authors = {
        "jiangnan-night-market-guide": "lena",
        "small-team-retrospective-rhythm": "marcus",
        "balcony-herb-garden-notes": "yara",
        "museum-audio-guide-notes": "lena",
        "river-cleanup-field-log": "marcus",
        "late-subway-essay-draft": "yara",
        "unsupported-health-routine-thread": "yara",
        "weekday-breakfast-walks": "qiao",
        "community-library-redesign": "ming",
        "weekend-ceramics-class-journal": "siyan",
        "old-town-breakfast-map": "lena",
        "freelance-invoice-notes": "owen",
    }
    for item in ARTICLES:
        article = await articles_repo.create_article(
            slug=item.slug,
            title=item.title,
            description=item.description,
            body=item.body,
            author=users[article_authors[item.slug]],
            tags=item.tags,
            content_status=item.content_status,
        )
        await articles_repo.create_moderation_log(
            article=article,
            analysis=article_analysis(item),
            allowed=item.review_status != "rejected",
            review_status=item.review_status,
        )
        seeded[item.slug] = article
    return seeded


async def seed_comments(comments_repo: CommentsRepository, governance_repo: GovernanceRepository, articles, users):
    seeded = []
    for item in COMMENTS:
        comment = await comments_repo.create_comment_for_article(
            body=item.body,
            article=articles[item.article_slug],
            user=users[item.username],
            content_status=item.content_status,
        )
        await comments_repo.create_moderation_log(
            body=item.body,
            article=articles[item.article_slug],
            user=users[item.username],
            moderation=comment_analysis(item),
            comment=comment,
            review_status=item.review_status,
        )
        if item.content_status == "pending":
            await governance_repo.create_audit_log(
                content_type="comment",
                article_id=articles[item.article_slug].id_,
                comment_id=comment.id_,
                actor=users["admin"],
                action="ai_pending_review",
                from_status="draft",
                to_status="pending",
                note="该评论被自动送入人工复核队列。",
                metadata={"commentBody": item.body},
            )
            await governance_repo.create_notification(
                user_id=users[item.username].id_,
                notification_type="comment_pending_review",
                title="评论已进入待审核",
                body="系统认为这条评论需要人工复核，结果出来后会再通知你。",
                content_type="comment",
                article_id=articles[item.article_slug].id_,
                comment_id=comment.id_,
            )
        if item.review_status == "rejected":
            await governance_repo.create_audit_log(
                content_type="comment",
                article_id=articles[item.article_slug].id_,
                comment_id=comment.id_,
                actor=users["admin"],
                action="moderation_reject",
                from_status="pending",
                to_status="hidden",
                note=item.note or "该评论因攻击性表述被驳回。",
                metadata={"commentBody": item.body},
            )
            await governance_repo.create_notification(
                user_id=users[item.username].id_,
                notification_type="moderation_reject",
                title="评论审核未通过",
                body="管理员认为这条评论不适合公开显示，可调整语气后重新参与讨论。",
                content_type="comment",
                article_id=articles[item.article_slug].id_,
                comment_id=comment.id_,
            )
        seeded.append(comment)
    return seeded


async def seed_reports(governance_repo: GovernanceRepository, articles, comments, users):
    comment_lookup = {comment.body: comment for comment in comments}
    target_comment = comment_lookup[
        "这篇的气氛已经有了，但现在确实有点一直围着同一种情绪打转，细节再多一点会更稳。"
    ]
    report = await governance_repo.create_comment_report(
        article=articles["late-subway-essay-draft"],
        comment=target_comment,
        reporter=users["lena"],
        reason="tone",
        detail="语气有点尖锐，但我不确定是否真的需要隐藏。",
    )
    transition = await governance_repo.review_report(
        report_id=report.id,
        action="ignore",
        actor=users["admin"],
        note="保留观点，暂不采纳举报。",
    )
    await governance_repo.create_audit_log(
        content_type=transition["content_type"],
        article_id=transition["article_id"],
        comment_id=transition["comment_id"],
        actor=users["admin"],
        action="report_ignore",
        from_status=transition["from_status"],
        to_status=transition["to_status"],
        note="保留观点，暂不采纳举报。",
        metadata=transition.get("metadata"),
    )
    await governance_repo.create_notification(
        user_id=users["owen"].id_,
        notification_type="report_ignore",
        title="举报结果",
        body="管理员已驳回举报请求，评论状态未变。处理备注：保留观点，暂不采纳举报。",
        content_type="comment",
        article_id=transition["article_id"],
        comment_id=transition["comment_id"],
    )

    article_report = await governance_repo.create_article_report(
        article=articles["unsupported-health-routine-thread"],
        reporter=users["yara"],
        reason="unsafe",
        detail="内容存在未经证实的健康建议，应该保持隐藏。",
    )
    article_transition = await governance_repo.review_report(
        report_id=article_report.id,
        action="hide",
        actor=users["admin"],
        note="已采纳举报，继续保持隐藏。",
    )
    await governance_repo.create_audit_log(
        content_type=article_transition["content_type"],
        article_id=article_transition["article_id"],
        comment_id=article_transition["comment_id"],
        actor=users["admin"],
        action="report_hide",
        from_status=article_transition["from_status"],
        to_status=article_transition["to_status"],
        note="已采纳举报，继续保持隐藏。",
        metadata=article_transition.get("metadata"),
    )
    await governance_repo.create_notification(
        user_id=users["yara"].id_,
        notification_type="report_hide",
        title="举报结果",
        body="管理员已接受举报请求，文章已设为不公开显示。处理备注：已采纳举报，继续保持隐藏。",
        content_type="article",
        article_id=article_transition["article_id"],
    )


async def seed_engagement(conn: asyncpg.Connection, articles, comments, users) -> None:
    for slug, username in ARTICLE_FAVORITES:
        await conn.execute(
            """
            INSERT INTO favorites (user_id, article_id)
            VALUES ($1, $2)
            ON CONFLICT DO NOTHING
            """,
            users[username].id_,
            articles[slug].id_,
        )
    comment_lookup = {comment.body: comment for comment in comments}
    for body, username in COMMENT_LIKES:
        comment = comment_lookup.get(body)
        if not comment:
            continue
        await conn.execute(
            """
            INSERT INTO comment_likes (user_id, comment_id)
            VALUES ($1, $2)
            ON CONFLICT DO NOTHING
            """,
            users[username].id_,
            comment.id_,
        )


async def seed_manual_notifications(governance_repo: GovernanceRepository, articles, users):
    await governance_repo.create_notification(
        user_id=users["lena"].id_,
        notification_type="article_pending_review",
        title="文章已进入待审核",
        body="《末班地铁里那些短暂又亲密的片刻》正在等待人工复核。",
        content_type="article",
        article_id=articles["late-subway-essay-draft"].id_,
    )
    await governance_repo.create_notification(
        user_id=users["marcus"].id_,
        notification_type="moderation_approve",
        title="评论审核已通过",
        body="你在《小团队怎么把复盘会开得不空不散》下的评论已公开显示。",
        content_type="comment",
        article_id=articles["small-team-retrospective-rhythm"].id_,
    )
    await governance_repo.create_notification(
        user_id=users["lena"].id_,
        notification_type="digest",
        title="本周互动概览",
        body="你的几篇文章本周收到不少互动，其中夜市指南仍然是阅读量最高的一篇。",
        content_type="article",
        article_id=articles["jiangnan-night-market-guide"].id_,
    )
    await governance_repo.connection.execute(
        """
        UPDATE user_notifications
        SET is_read = TRUE,
            read_at = now() - interval '2 hours'
        WHERE (
                user_id = $1
            AND notification_type = 'digest'
        )
           OR (
                user_id = $2
            AND notification_type = 'moderation_approve'
        )
        """,
        users["lena"].id_,
        users["marcus"].id_,
    )


async def main() -> None:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required for seeding demo data.")
    conn = await asyncpg.connect(database_url)
    try:
        users_repo = UsersRepository(conn)
        articles_repo = ArticlesRepository(conn)
        comments_repo = CommentsRepository(conn)
        governance_repo = GovernanceRepository(conn)

        async with conn.transaction():
            await purge_existing_demo_data(conn)
            users = await seed_users(users_repo)
            articles = await seed_articles(articles_repo, users)
            comments = await seed_comments(comments_repo, governance_repo, articles, users)
            await seed_reports(governance_repo, articles, comments, users)
            await seed_engagement(conn, articles, comments, users)
            await seed_manual_notifications(governance_repo, articles, users)
    finally:
        await conn.close()

    print("Seeded realistic demo data into", database_url)


if __name__ == "__main__":
    asyncio.run(main())
