# -*- coding: utf-8 -*-
"""
模拟电商数仓数据生成脚本

职责：
    1. 在 dw_ecom 库重建 5 张数仓表（DROP + CREATE）
    2. 生成贴近真实电商业务分布的模拟数据并批量插入：
       - dw_categories  约 200 行（8 个一级类目，二级类目 20-30 个/个）
       - dw_products    2000 行（品牌+类目+修饰词组合命名）
       - dw_users       10 万行（城市加权分布）
       - dw_orders      约 50 万行（近 13 个月，含双11/618/双12 促销放大）
       - dw_traffic     约 30 万行（日期 × 渠道 × 商品抽样）
    3. 打印各表行数统计

运行方式（项目根目录）：
    python scripts/init_dw_data.py
"""
import math
import random
import sys
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

# 将项目根目录加入 sys.path，保证脚本可独立运行并导入 app 包
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, text

from app.core.config import get_settings
from app.core.logger import logger, setup_logger

# 固定随机种子，保证每次生成的数据一致（便于核验与回归）
random.seed(42)

# =====================================================================
# 业务词典（模拟数据的取值来源，与 YAML 元数据 examples 保持一致）
# =====================================================================

# 一级类目 → 二级类目列表
CATEGORY_TREE = {
    "美妆护肤": ["口红", "粉底液", "眼影", "睫毛膏", "卸妆水", "面膜", "精华液", "乳液", "面霜", "防晒霜",
                "香水", "腮红", "眉笔", "眼线笔", "散粉", "定妆喷雾", "身体乳", "护手霜", "洗发水", "沐浴露",
                "化妆棉", "美容仪器", "美甲用品", "假睫毛", "唇釉"],
    "数码家电": ["手机", "笔记本电脑", "平板电脑", "智能手表", "蓝牙耳机", "音箱", "电视机", "空调", "冰箱",
                "洗衣机", "电饭煲", "微波炉", "吸尘器", "电吹风", "电动牙刷", "路由器", "充电宝", "键盘", "鼠标",
                "显示器", "摄像机", "无人机", "智能门锁", "加湿器", "破壁机"],
    "服饰鞋包": ["羽绒服", "毛衣", "T恤", "衬衫", "牛仔裤", "休闲裤", "连衣裙", "半身裙", "西装", "风衣",
                "运动鞋", "板鞋", "高跟鞋", "凉鞋", "双肩包", "手提包", "钱包", "皮带", "围巾", "帽子",
                "袜子", "睡衣", "泳装", "冲锋衣", "卫衣"],
    "食品饮料": ["坚果零食", "饼干糕点", "糖果巧克力", "牛肉干", "薯片", "方便面", "气泡水", "果汁", "咖啡",
                "奶茶", "牛奶", "酸奶", "白酒", "啤酒", "红酒", "大米", "食用油", "调味料", "方便速食", "罐头",
                "蜂蜜", "燕麦", "蛋白粉", "茶叶", "膨化食品"],
    "母婴亲子": ["纸尿裤", "婴儿奶粉", "婴儿湿巾", "奶瓶", "儿童玩具", "积木", "童装", "童鞋", "儿童绘本",
                "辅食", "儿童安全座椅", "婴儿车", "婴儿床", "儿童牙刷", "孕妇装", "待产用品", "儿童水杯",
                "安抚玩偶", "早教机", "儿童文具", "书包", "儿童口罩", "驱蚊用品", "儿童面霜", "婴儿洗发水"],
    "家居日用": ["纸巾", "垃圾袋", "洗衣液", "洗洁精", "消毒液", "收纳盒", "保温杯", "马克杯", "四件套",
                "被子", "枕头", "毛巾", "拖鞋", "香薰蜡烛", "空气清新剂", "除湿袋", "挂钩", "雨伞", "坐垫",
                "窗帘", "地毯", "花瓶", "餐具", "砧板", "刀具"],
    "运动户外": ["跑步鞋", "瑜伽垫", "瑜伽服", "运动水壶", "跳绳", "哑铃", "筋膜枪", "护膝", "运动手环",
                "帐篷", "睡袋", "登山杖", "钓竿", "渔具", "自行车", "滑板", "泳镜", "泳衣", "羽毛球拍",
                "网球拍", "篮球", "足球", "运动腰包", "防晒帽", "登山鞋"],
    "宠物生活": ["猫粮", "狗粮", "猫砂", "宠物零食", "猫罐头", "狗罐头", "宠物玩具", "猫爬架", "狗窝",
                "宠物牵引绳", "宠物沐浴露", "宠物梳子", "猫抓板", "宠物服装", "自动喂食器", "饮水机",
                "宠物尿垫", "洁齿骨", "驱虫药", "营养膏", "化毛膏", "宠物窝垫", "猫条", "宠物背包", "鸟粮"],
}

# 类目 → 品牌列表
CATEGORY_BRANDS = {
    "美妆护肤": ["完美日记", "花西子", "珀莱雅", "薇诺娜", "欧莱雅"],
    "数码家电": ["华为", "小米", "苹果", "格力", "美的"],
    "服饰鞋包": ["优衣库", "耐克", "李宁", "波司登", "森马"],
    "食品饮料": ["三只松鼠", "元气森林", "伊利", "良品铺子"],
    "母婴亲子": ["babycare", "飞鹤", "好奇"],
    "家居日用": ["全棉时代", "名创优品", "心相印"],
    "运动户外": ["迪卡侬", "安踏", "始祖鸟"],
    "宠物生活": ["皇家", "卫仕", "麦富迪"],
}

# 类目 → 价格区间（元）
CATEGORY_PRICE_RANGE = {
    "美妆护肤": (49.9, 499.0),
    "数码家电": (99.0, 9999.0),
    "服饰鞋包": (59.0, 999.0),
    "食品饮料": (9.9, 99.0),
    "母婴亲子": (29.9, 799.0),
    "家居日用": (9.9, 199.0),
    "运动户外": (39.9, 1999.0),
    "宠物生活": (19.9, 399.0),
}

# 商品名修饰词
PRODUCT_SUFFIX = ["经典款", "新款", "旗舰款", "限定款", "礼盒装", "套装", "加大款", "迷你款", "升级版", "联名款"]

# 渠道及下单权重
CHANNELS = {"淘宝": 0.30, "抖音": 0.25, "京东": 0.20, "拼多多": 0.15, "小程序": 0.10}

# 城市及用户分布权重（一线/新一线为主）
CITIES = {
    "北京": 12, "上海": 13, "广州": 10, "深圳": 12, "杭州": 8,
    "成都": 7, "武汉": 6, "南京": 5, "重庆": 6, "西安": 4,
    "苏州": 4, "长沙": 4, "郑州": 3, "天津": 3, "青岛": 3,
}

# 会员等级及分布权重
USER_LEVELS = {"普通会员": 60, "银卡会员": 25, "金卡会员": 10, "钻石会员": 5}

# 订单状态及分布权重
ORDER_STATUSES = {"已完成": 78, "已退款": 12, "待付款": 5, "已发货": 5}

# 数据日期范围：近 13 个月（今天为 2026-11-09，保证"昨天"有数据）
START_DATE = date(2025, 11, 1)
END_DATE = date(2026, 11, 8)

BATCH_SIZE = 5000  # 批量插入行数


def weighted_choice(mapping: dict) -> str:
    """按权重随机选取一个键

    Args:
        mapping: {选项: 权重} 字典

    Returns:
        被选中的选项
    """
    keys = list(mapping.keys())
    weights = list(mapping.values())
    return random.choices(keys, weights=weights, k=1)[0]


def pick_promo_multiplier(d: date) -> float:
    """计算某天的订单量放大倍数（促销日效应）

    Args:
        d: 日期

    Returns:
        放大倍数（1.0 为平日）
    """
    if d == date(2025, 11, 11):
        return 7.0       # 双11 当天
    if d == date(2026, 6, 18):
        return 5.0       # 618 当天
    if d == date(2025, 12, 12):
        return 2.0       # 双12
    if d == date(2026, 5, 20):
        return 1.8       # 520
    if date(2026, 11, 1) <= d <= date(2026, 11, 11):
        return 2.5       # 双11 大促季
    if d.weekday() >= 5:
        return 1.3       # 周末
    return 1.0


def create_tables(engine) -> None:
    """重建 dw_ecom 库的 5 张数仓表

    Args:
        engine: SQLAlchemy 引擎（连接 dw_ecom 库）
    """
    ddl_statements = [
        """
        DROP TABLE IF EXISTS dw_orders;
        CREATE TABLE dw_orders (
            order_id        VARCHAR(32)  NOT NULL COMMENT '订单ID',
            user_id         BIGINT       NOT NULL COMMENT '用户ID',
            product_id      BIGINT       NOT NULL COMMENT '商品ID',
            channel         VARCHAR(32)  NOT NULL COMMENT '下单渠道',
            brand           VARCHAR(64)  NOT NULL COMMENT '品牌',
            order_status    VARCHAR(16)  NOT NULL COMMENT '订单状态',
            order_amount    DECIMAL(12,2) NOT NULL COMMENT '订单金额',
            discount_amount DECIMAL(12,2) NOT NULL DEFAULT 0 COMMENT '优惠金额',
            pay_amount      DECIMAL(12,2) NOT NULL COMMENT '支付金额',
            refund_amount   DECIMAL(12,2) NOT NULL DEFAULT 0 COMMENT '退款金额',
            quantity        INT          NOT NULL DEFAULT 1 COMMENT '购买数量',
            order_date      DATE         NOT NULL COMMENT '下单日期',
            pay_date        DATE         NULL COMMENT '支付日期',
            PRIMARY KEY (order_id),
            KEY idx_order_date (order_date),
            KEY idx_pay_date (pay_date),
            KEY idx_brand (brand),
            KEY idx_user (user_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='订单事实表';
        """,
        """
        DROP TABLE IF EXISTS dw_products;
        CREATE TABLE dw_products (
            product_id    BIGINT        NOT NULL COMMENT '商品ID',
            product_name  VARCHAR(128)  NOT NULL COMMENT '商品名称',
            category_id   INT           NOT NULL COMMENT '类目ID',
            brand         VARCHAR(64)   NOT NULL COMMENT '品牌',
            price         DECIMAL(10,2) NOT NULL COMMENT '商品单价',
            stock         INT           NOT NULL DEFAULT 0 COMMENT '库存',
            shelf_date    DATE          NOT NULL COMMENT '上架日期',
            PRIMARY KEY (product_id),
            KEY idx_brand (brand),
            KEY idx_category (category_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='商品维表';
        """,
        """
        DROP TABLE IF EXISTS dw_users;
        CREATE TABLE dw_users (
            user_id       BIGINT      NOT NULL COMMENT '用户ID',
            user_name     VARCHAR(64) NOT NULL COMMENT '用户昵称',
            gender        VARCHAR(8)  NOT NULL COMMENT '性别',
            age           INT         NOT NULL COMMENT '年龄',
            city          VARCHAR(32) NOT NULL COMMENT '城市',
            user_level    VARCHAR(16) NOT NULL COMMENT '会员等级',
            register_date DATE        NOT NULL COMMENT '注册日期',
            PRIMARY KEY (user_id),
            KEY idx_city (city),
            KEY idx_level (user_level)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='用户维表';
        """,
        """
        DROP TABLE IF EXISTS dw_categories;
        CREATE TABLE dw_categories (
            category_id          INT         NOT NULL COMMENT '类目ID',
            category_name        VARCHAR(64) NOT NULL COMMENT '类目名称',
            parent_category_id   INT         NULL COMMENT '父类目ID',
            parent_category_name VARCHAR(64) NULL COMMENT '一级类目名称',
            PRIMARY KEY (category_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='类目维表';
        """,
        """
        DROP TABLE IF EXISTS dw_traffic;
        CREATE TABLE dw_traffic (
            id         BIGINT      NOT NULL AUTO_INCREMENT COMMENT '自增主键',
            stat_date  DATE        NOT NULL COMMENT '统计日期',
            channel    VARCHAR(32) NOT NULL COMMENT '流量渠道',
            product_id BIGINT      NOT NULL COMMENT '商品ID',
            pv         INT         NOT NULL COMMENT '浏览量',
            uv         INT         NOT NULL COMMENT '访客数',
            PRIMARY KEY (id),
            KEY idx_stat_date (stat_date),
            KEY idx_channel (channel)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='流量事实表';
        """,
    ]
    with engine.begin() as conn:
        for ddl in ddl_statements:
            conn.execute(text(ddl))
    logger.info("5 张数仓表重建完成")


def batch_insert(conn, sql: str, rows: list[tuple], table_label: str) -> int:
    """分批批量插入数据

    Args:
        conn: SQLAlchemy 连接
        sql: 含占位符的 INSERT 语句
        rows: 行元组列表
        table_label: 表名（用于日志）

    Returns:
        插入总行数
    """
    total = 0
    for i in range(0, len(rows), BATCH_SIZE):
        chunk = rows[i:i + BATCH_SIZE]
        conn.execute(sql, chunk)  # executemany：一次多行
        total += len(chunk)
    logger.info("{} 插入完成: {} 行", table_label, total)
    return total


def gen_categories(engine) -> dict:
    """生成类目维表数据

    Args:
        engine: SQLAlchemy 引擎

    Returns:
        {二级类目名: (category_id, 一级类目名)} 映射，供商品表生成引用
    """
    rows = []
    sub_index = {}  # 二级类目名 → (id, 一级类目名)
    cid = 100
    for parent, subs in CATEGORY_TREE.items():
        pid = cid
        rows.append((cid, parent, None, None))  # 一级类目行
        cid += 1
        for sub in subs:
            rows.append((cid, sub, pid, parent))
            sub_index[sub] = (cid, parent)
            cid += 1
    with engine.begin() as conn:
        batch_insert(
            conn,
            text("INSERT INTO dw_categories (category_id, category_name, parent_category_id, parent_category_name) VALUES (:a, :b, :c, :d)"),
            rows, "dw_categories",
        )
    return sub_index


def gen_products(engine, sub_index: dict) -> list[dict]:
    """生成商品维表数据

    Args:
        engine: SQLAlchemy 引擎
        sub_index: 二级类目映射（来自 gen_categories）

    Returns:
        商品列表 [{product_id, product_name, category_id, brand, price}, ...]
    """
    products = []
    pid = 200001
    # 按类目均衡生成商品：每个二级类目分配 2000/类目数 个商品
    all_subs = [(parent, sub) for parent, subs in CATEGORY_TREE.items() for sub in subs]
    per_sub = 2000 // len(all_subs)
    remainder = 2000 - per_sub * len(all_subs)

    for i, (parent, sub) in enumerate(all_subs):
        count = per_sub + (1 if i < remainder else 0)
        cat_id, _ = sub_index[sub]
        brands = CATEGORY_BRANDS[parent]
        low, high = CATEGORY_PRICE_RANGE[parent]
        for _ in range(count):
            brand = random.choice(brands)
            price = round(random.uniform(low, high), 2)
            name = f"{brand}{sub}{random.choice(PRODUCT_SUFFIX)}"
            products.append({
                "product_id": pid,
                "product_name": name,
                "category_id": cat_id,
                "brand": brand,
                "price": price,
            })
            pid += 1
    random.shuffle(products)

    rows = [
        (p["product_id"], p["product_name"], p["category_id"], p["brand"],
         p["price"], random.randint(100, 5000), START_DATE - timedelta(days=random.randint(30, 400)))
        for p in products
    ]
    with engine.begin() as conn:
        batch_insert(
            conn,
            text("INSERT INTO dw_products VALUES (:a, :b, :c, :d, :e, :f, :g)"),
            rows, "dw_products",
        )
    return products


def gen_users(engine) -> int:
    """生成用户维表数据（10 万行）

    Args:
        engine: SQLAlchemy 引擎

    Returns:
        插入的用户数
    """
    rows = []
    for uid in range(100001, 100001 + 100000):
        rows.append((
            uid,
            f"用户{uuid.uuid4().hex[:6]}",
            random.choices(["男", "女"], weights=[45, 55], k=1)[0],
            random.randint(16, 55),
            weighted_choice(CITIES),
            weighted_choice(USER_LEVELS),
            START_DATE - timedelta(days=random.randint(60, 700)),
        ))
    with engine.begin() as conn:
        batch_insert(
            conn,
            text("INSERT INTO dw_users VALUES (:a, :b, :c, :d, :e, :f, :g)"),
            rows, "dw_users",
        )
    return len(rows)


def gen_orders(engine, products: list[dict]) -> int:
    """生成订单事实表数据（约 50 万行，含促销日放大）

    采用流式生成：每攒满 BATCH_SIZE 行立即插入，避免 50 万行全部驻留内存。

    Args:
        engine: SQLAlchemy 引擎
        products: 商品列表（来自 gen_products）

    Returns:
        插入的订单数
    """
    user_ids = list(range(100001, 100001 + 100000))
    channel_names = list(CHANNELS.keys())
    channel_weights = list(CHANNELS.values())
    status_names = list(ORDER_STATUSES.keys())
    status_weights = list(ORDER_STATUSES.values())

    insert_sql = text(
        "INSERT INTO dw_orders (order_id, user_id, product_id, channel, brand, order_status, "
        "order_amount, discount_amount, pay_amount, refund_amount, quantity, order_date, pay_date) "
        "VALUES (:a, :b, :c, :d, :e, :f, :g, :h, :i, :j, :k, :l, :m)"
    )

    total_days = (END_DATE - START_DATE).days + 1
    total = 0
    buffer: list[tuple] = []

    with engine.begin() as conn:
        for offset in range(total_days):
            d = START_DATE + timedelta(days=offset)
            daily_cnt = int(1100 * pick_promo_multiplier(d) * random.uniform(0.8, 1.2))
            for _ in range(daily_cnt):
                product = random.choice(products)
                quantity = random.choices([1, 2, 3, 5], weights=[55, 25, 12, 8], k=1)[0]
                order_amount = round(product["price"] * quantity, 2)
                discount = round(order_amount * random.uniform(0, 0.2), 2)
                pay_amount = round(order_amount - discount, 2)
                status = random.choices(status_names, weights=status_weights, k=1)[0]
                refund = pay_amount if status == "已退款" else 0.0

                # 下单时刻：全天随机；支付日期=下单当天为主，少数次日（待付款为空）
                order_ts = datetime.combine(d, datetime.min.time()) + timedelta(
                    seconds=random.randint(0, 86399)
                )
                pay_date = None
                if status != "待付款":
                    pay_d = d + timedelta(days=1) if random.random() < 0.08 else d
                    pay_date = pay_d

                order_id = f"ORD{order_ts.strftime('%Y%m%d%H%M%S')}{random.randint(100000, 999999)}"
                buffer.append((
                    order_id, random.choice(user_ids), product["product_id"],
                    random.choices(channel_names, weights=channel_weights, k=1)[0],
                    product["brand"], status,
                    order_amount, discount, pay_amount, refund, quantity,
                    d, pay_date,
                ))
                if len(buffer) >= BATCH_SIZE:
                    conn.execute(insert_sql, buffer)
                    total += len(buffer)
                    buffer.clear()

            # 每 30 天打印一次进度，便于观察造数进度
            if (offset + 1) % 30 == 0 or offset == total_days - 1:
                logger.info("订单生成进度: {}/{} 天，已插入 {} 行", offset + 1, total_days, total)
        if buffer:
            conn.execute(insert_sql, buffer)
            total += len(buffer)

    logger.info("dw_orders 插入完成: {} 行", total)
    return total


def gen_traffic(engine, products: list[dict]) -> int:
    """生成流量事实表数据（约 30 万行：每天 5 渠道 × 160 商品抽样）

    采用流式生成，避免大列表驻留内存。

    Args:
        engine: SQLAlchemy 引擎
        products: 商品列表

    Returns:
        插入的流量记录数
    """
    channel_names = list(CHANNELS.keys())
    insert_sql = text(
        "INSERT INTO dw_traffic (stat_date, channel, product_id, pv, uv) VALUES (:a, :b, :c, :d, :e)"
    )

    total_days = (END_DATE - START_DATE).days + 1
    total = 0
    buffer: list[tuple] = []

    with engine.begin() as conn:
        for offset in range(total_days):
            d = START_DATE + timedelta(days=offset)
            promo = pick_promo_multiplier(d)
            for channel in channel_names:
                sampled = random.sample(products, 160)
                for product in sampled:
                    base_pv = int(math.exp(random.uniform(math.log(200), math.log(20000))))
                    pv = int(base_pv * promo)
                    uv = max(1, int(pv / random.uniform(1.5, 3.0)))
                    buffer.append((d, channel, product["product_id"], pv, uv))
                    if len(buffer) >= BATCH_SIZE:
                        conn.execute(insert_sql, buffer)
                        total += len(buffer)
                        buffer.clear()
            if (offset + 1) % 30 == 0 or offset == total_days - 1:
                logger.info("流量生成进度: {}/{} 天，已插入 {} 行", offset + 1, total_days, total)
        if buffer:
            conn.execute(insert_sql, buffer)
            total += len(buffer)

    logger.info("dw_traffic 插入完成: {} 行", total)
    return total


def verify_counts(engine) -> dict:
    """验证各表行数

    Args:
        engine: SQLAlchemy 引擎

    Returns:
        {表名: 行数}
    """
    counts = {}
    with engine.connect() as conn:
        for table in ["dw_categories", "dw_products", "dw_users", "dw_orders", "dw_traffic"]:
            counts[table] = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
    return counts


def main() -> None:
    """脚本主入口：建表 → 造数 → 校验统计"""
    setup_logger(level="INFO")
    settings = get_settings()
    engine = create_engine(settings.mysql.url_for(settings.mysql.dw_database))

    logger.info("========== 开始生成模拟电商数据 ==========")
    start = datetime.now()

    create_tables(engine)
    sub_index = gen_categories(engine)
    products = gen_products(engine, sub_index)
    gen_users(engine)
    order_cnt = gen_orders(engine, products)
    gen_traffic(engine, products)

    counts = verify_counts(engine)
    cost = (datetime.now() - start).total_seconds()
    logger.info("========== 生成完成，耗时 {:.1f}s ==========", cost)
    for table, cnt in counts.items():
        logger.info("{}: {} 行", table, cnt)
    logger.info("订单总量: {} (期望约 50 万)", order_cnt)

    engine.dispose()


if __name__ == "__main__":
    main()
