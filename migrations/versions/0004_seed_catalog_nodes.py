"""seed the four supported textbook catalog trees.

The paths are the textbook paths present in the current grade 1/2 knowledge
point workbooks.  Keeping them in a migration makes ``make db-init`` usable
without requiring the source workbooks at runtime.
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import select

from app.models import CatalogNode, TextbookEdition
from app.models.base import utc_now

revision = "0004_seed_catalog_nodes"
down_revision = "0003_v1_revision_model"
branch_labels = None
depends_on = None

CATALOG_PATHS = {
    "pep_math_2024_g1_t1": (
        "数学游戏",
        "5以内数的认识和加、减法/1~5的认识",
        "5以内数的认识和加、减法/比大小",
        "5以内数的认识和加、减法/第几",
        "5以内数的认识和加、减法/分与合",
        "5以内数的认识和加、减法/加法",
        "5以内数的认识和加、减法/减法",
        "5以内数的认识和加、减法/0的认识和加、减法",
        "6~10的认识和加、减法/6~9的认识",
        "6~10的认识和加、减法/6和7的加、减法",
        "6~10的认识和加、减法/8和9的加、减法",
        "6~10的认识和加、减法/用加法解决问题",
        "6~10的认识和加、减法/用减法解决问题",
        "6~10的认识和加、减法/10的认识",
        "6~10的认识和加、减法/10的加、减法",
        "6~10的认识和加、减法/连加、连减",
        "6~10的认识和加、减法/加、减混合",
        "6~10的认识和加、减法/解决问题",
        "认识立体图形",
        "认识立体图形/拼一拼",
        "11~20的认识/11~20的认识",
        "11~20的认识/简单加、减法",
        "20以内的进位加法",
        "20以内的进位加法/9加几",
        "20以内的进位加法/8、7、6加几",
        "20以内的进位加法/5、4、3、2加几",
        "20以内的进位加法/解决问题",
        "20以内的进位加法/应用提升",
    ),
    "pep_math_2024_g1_t2": (
        "认识平面图形",
        "认识平面图形/七巧板",
        "20以内的退位减法",
        "20以内的退位减法/十几减9",
        "20以内的退位减法/十几减8、7、6",
        "20以内的退位减法/十几减5、4、3、2",
        "20以内的退位减法/解决问题",
        "100以内数的认识/数数",
        "100以内数的认识/数的组成",
        "100以内数的认识/数的读写",
        "100以内数的认识/数的顺序、比较大小",
        "100以内数的认识/数的组成、数的读写",
        "100以内数的认识/简单的加、减法",
        "100以内数的认识/摆一摆，想一想",
        "100以内的口算加、减法/口算加法",
        "100以内的口算加、减法/口算减法",
        "100以内的笔算加、减法/笔算加法",
        "100以内的笔算加、减法/笔算减法",
        "数量间的加减关系",
        "数量间的加减关系/试卷拓展（待教材核验）",
        "欢乐购物街/认识人民币",
        "欢乐购物街/买卖我做主",
    ),
    "pep_math_2024_g2_t1": (
        "分类与整理/按给定标准分类",
        "分类与整理/自选标准分类和简单统计表",
        "分类与整理/逐层分类",
        "分类与整理/练习与综合应用",
        "1~6的表内乘法/乘法的初步认识",
        "1~6的表内乘法/2~6的乘法口诀/5的乘法口诀",
        "1~6的表内乘法/2~6的乘法口诀/2、3、4的乘法口诀",
        "1~6的表内乘法/2~6的乘法口诀/6的乘法口诀",
        "1~6的表内乘法/2~6的乘法口诀/乘加、乘减",
        "1~6的表内乘法/解决问题",
        "1~6的表内除法/除法的初步认识/除法",
        "1~6的表内除法/除法的初步认识/平均分",
        "1~6的表内除法/用2~6的乘法口诀求商",
        "1~6的表内除法/解决问题",
        "综合与实践/校园小导游/认识东、南、西、北",
        "综合与实践/校园小导游/校园小导游",
        "综合与实践/校园小导游/小讲堂",
        "厘米和米",
        "厘米和米/整理和复习",
        "综合与实践/身体上的尺子/身体上的长度",
        "综合与实践/身体上的尺子/身体上的尺子",
        "综合与实践/身体上的尺子/小讲堂",
        "7~9的表内乘、除法/7~9的乘法口诀",
        "7~9的表内乘、除法/用7~9的乘法口诀求商",
        "7~9的表内乘、除法/整理和复习",
        "7~9的表内乘、除法/解决问题",
    ),
    "pep_math_2024_g2_t2": (
        "综合与实践/时间在哪里/认识时间",
        "综合与实践/时间在哪里/我与时间的故事",
        "综合与实践/时间在哪里/我的时间小书",
        "综合与实践/时间在哪里/小讲堂",
        "有余数的除法/有余数的除法",
        "有余数的除法/余数和除数的关系",
        "有余数的除法/有余数除法的竖式",
        "有余数的除法/有余数除法的实际应用",
        "数量间的乘除关系/数量间的乘除关系",
        "数量间的乘除关系/解决实际问题",
        "数量间的乘除关系/根据已知条件补充问题",
        "数量间的乘除关系/根据问题补充合适条件",
        "万以内数的认识/1000以内数的认识",
        "万以内数的认识/10000以内数的认识",
        "万以内数的认识/10000以内数的认识/数的大小比较",
        "万以内数的认识/10000以内数的认识/近似数",
        "万以内数的认识/简单的加、减法",
        "万以内的加法和减法/加法",
        "万以内的加法和减法/减法",
        "万以内的加法和减法/加减法各部分间的关系",
        "万以内的加法和减法/数独游戏",
        "综合与实践/数学连环画/连环画分享会",
        "综合与实践/数学连环画/我是小画家",
        "综合与实践/数学连环画/小小故事会",
    ),
}


def _insert_node(
    bind,
    edition_id: int,
    source_key: str,
    parent_id: int | None,
    level: int,
    node_type: str,
    source_path: str | None,
    title: str,
    sort_order: int,
) -> int:
    existing = bind.execute(
        select(CatalogNode.id).where(
            CatalogNode.edition_id == edition_id,
            CatalogNode.source_key == source_key,
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    result = bind.execute(
        CatalogNode.__table__.insert().values(
            edition_id=edition_id,
            parent_id=parent_id,
            level=level,
            node_type=node_type,
            source_key=source_key,
            source_path=source_path,
            title=title,
            sort_order=sort_order,
            row_version=1,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
    )
    return result.inserted_primary_key[0]


def upgrade() -> None:
    bind = op.get_bind()
    for edition_code, paths in CATALOG_PATHS.items():
        edition_id = bind.execute(
            select(TextbookEdition.id).where(
                TextbookEdition.edition_code == edition_code
            )
        ).scalar_one_or_none()
        if edition_id is None:
            continue

        root_id = _insert_node(
            bind,
            edition_id,
            "book",
            None,
            0,
            "book",
            None,
            edition_code,
            0,
        )
        node_ids = {"": root_id}
        child_orders: dict[str, int] = {}
        for path in paths:
            parts = path.split("/")
            parent_key = ""
            for index, title in enumerate(parts, start=1):
                key = "/".join(parts[:index])
                if key in node_ids:
                    parent_key = key
                    continue
                child_orders[parent_key] = child_orders.get(parent_key, -1) + 1
                node_ids[key] = _insert_node(
                    bind,
                    edition_id,
                    key,
                    node_ids[parent_key],
                    index,
                    "unit" if index == 1 else "section",
                    key,
                    title,
                    child_orders[parent_key],
                )
                parent_key = key


def downgrade() -> None:
    bind = op.get_bind()
    for edition_code in CATALOG_PATHS:
        edition_id = bind.execute(
            select(TextbookEdition.id).where(
                TextbookEdition.edition_code == edition_code
            )
        ).scalar_one_or_none()
        if edition_id is not None:
            bind.execute(
                CatalogNode.__table__.delete().where(
                    CatalogNode.edition_id == edition_id
                )
            )
