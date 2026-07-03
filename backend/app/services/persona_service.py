"""人格 Service：管理导师风格人格的 CRUD 与预设初始化。

预设人格共 4 种，覆盖不同教学风格：
1. 严格导师：直接指出错误、不绕弯子、要求严谨
2. 鼓励型搭子：多用肯定、循序渐进、降低挫败感
3. 苏格拉底式：用问题引导用户自己发现答案
4. 费曼讲解员：用通俗类比解释、要求用户复述
"""
import json

from sqlalchemy.orm import Session

from app.common.logger import get_logger
from app.models.schemas import Persona, PersonaCreate, PersonaUpdate

logger = get_logger()


# 预设人格定义（source_content 与 parsed_prompt 使用 JSON 字符串）
_PRESETS: list[dict] = [
    {
        "name": "严格导师",
        "description": "直接指出错误、不绕弯子、要求严谨，适合需要快速纠错的学习场景。",
        "parsed_prompt": {
            "role": "你是一位严格的导师，关注学习严谨性与正确性。",
            "speaking_style": "直接、简洁、不绕弯子；发现错误立即指出，不做无意义铺垫。",
            "teaching_preferences": [
                "优先指出错误而非夸奖",
                "要求术语精确，不允许含糊表述",
                "对概念模糊处立即追问",
            ],
        },
    },
    {
        "name": "鼓励型搭子",
        "description": "多用肯定、循序渐进、降低挫败感，适合入门或信心不足的学习者。",
        "parsed_prompt": {
            "role": "你是一位鼓励型的学习搭子，注重降低学习焦虑。",
            "speaking_style": "多用肯定与共情，循序渐进拆解步骤，承认难度。",
            "teaching_preferences": [
                "先肯定用户的尝试再指出问题",
                "把大问题拆成小步骤，逐步引导",
                "遇到卡壳时给予情绪支持",
            ],
        },
    },
    {
        "name": "苏格拉底式",
        "description": "用问题引导用户自己发现答案，培养独立思考能力。",
        "parsed_prompt": {
            "role": "你是一位苏格拉底式导师，通过提问引导用户自行发现答案。",
            "speaking_style": "多反问、少直接给答案；每次回复尽量以问题收尾。",
            "teaching_preferences": [
                "用引导性问题代替直接讲解",
                "等用户思考后再补充",
                "在用户接近答案时点到为止",
            ],
        },
    },
    {
        "name": "费曼讲解员",
        "description": "用通俗类比解释概念，并要求用户复述以检验理解。",
        "parsed_prompt": {
            "role": "你是一位费曼讲解员，用最通俗的类比解释复杂概念。",
            "speaking_style": "多用生活类比，少用术语；解释后要求用户用自己的话复述。",
            "teaching_preferences": [
                "每个概念先用生活类比解释",
                "讲完即要求用户复述或举例",
                "复述不准确时再纠正",
            ],
        },
    },
]


def create_persona(db: Session, user_id: str, persona_data: PersonaCreate) -> Persona:
    """创建人格。

    Args:
        db: 数据库会话。
        user_id: 所属用户 ID。
        persona_data: 人格创建数据。

    Returns:
        Persona: 创建后的人格对象。
    """
    persona = Persona(
        user_id=user_id,
        name=persona_data.name,
        description=persona_data.description,
        source_type=persona_data.source_type,
        source_content=persona_data.source_content,
        parsed_prompt=persona_data.parsed_prompt,
        is_preset=False,
    )
    db.add(persona)
    db.commit()
    db.refresh(persona)
    logger.info(f"创建人格: id={persona.id}, user_id={user_id}, name={persona.name}")
    return persona


def get_persona(db: Session, persona_id: str, user_id: str) -> Persona | None:
    """查询单个人格（带用户鉴权，预设人格对所有人可见）。

    Args:
        db: 数据库会话。
        persona_id: 人格 ID。
        user_id: 用户 ID。

    Returns:
        Persona | None: 人格对象或 None。
    """
    persona = db.query(Persona).filter(Persona.id == persona_id).first()
    if persona is None:
        return None
    # 预设人格对所有用户可见；自定义人格仅归属用户可见
    if persona.is_preset or persona.user_id == user_id:
        return persona
    return None


def list_personas(db: Session, user_id: str) -> list[Persona]:
    """列出用户的所有人格（含预设）。

    Args:
        db: 数据库会话。
        user_id: 用户 ID。

    Returns:
        list[Persona]: 人格列表。
    """
    return (
        db.query(Persona)
        .filter((Persona.user_id == user_id) | (Persona.is_preset.is_(True)))
        .order_by(Persona.is_preset.desc(), Persona.created_at.asc())
        .all()
    )


def list_presets(db: Session) -> list[Persona]:
    """列出所有预设人格。

    Args:
        db: 数据库会话。

    Returns:
        list[Persona]: 预设人格列表。
    """
    return (
        db.query(Persona)
        .filter(Persona.is_preset.is_(True))
        .order_by(Persona.created_at.asc())
        .all()
    )


def update_persona(
    db: Session,
    persona_id: str,
    user_id: str,
    update_data: PersonaUpdate,
) -> Persona | None:
    """更新人格（预设人格不可更新）。

    Args:
        db: 数据库会话。
        persona_id: 人格 ID。
        user_id: 用户 ID。
        update_data: 待更新字段。

    Returns:
        Persona | None: 更新后的人格，不存在或不可改返回 None。
    """
    persona = db.query(Persona).filter(
        Persona.id == persona_id,
        Persona.user_id == user_id,
        Persona.is_preset.is_(False),
    ).first()
    if persona is None:
        return None

    update_fields = update_data.model_dump(exclude_unset=True)
    for field, value in update_fields.items():
        setattr(persona, field, value)

    db.commit()
    db.refresh(persona)
    logger.info(f"更新人格: id={persona_id}, fields={list(update_fields.keys())}")
    return persona


def delete_persona(db: Session, persona_id: str, user_id: str) -> bool:
    """删除人格（预设人格不可删除）。

    Args:
        db: 数据库会话。
        persona_id: 人格 ID。
        user_id: 用户 ID。

    Returns:
        bool: 是否删除成功。
    """
    persona = db.query(Persona).filter(
        Persona.id == persona_id,
        Persona.user_id == user_id,
        Persona.is_preset.is_(False),
    ).first()
    if persona is None:
        return False

    db.delete(persona)
    db.commit()
    logger.info(f"删除人格: id={persona_id}, user_id={user_id}")
    return True


def init_presets(db: Session) -> None:
    """初始化 4 种预设人格（幂等：已存在则跳过）。

    在应用启动时调用一次，确保系统内置人格可用。

    Args:
        db: 数据库会话。
    """
    existing_count = db.query(Persona).filter(Persona.is_preset.is_(True)).count()
    if existing_count >= len(_PRESETS):
        logger.debug(f"预设人格已存在 {existing_count} 个，跳过初始化。")
        return

    for preset in _PRESETS:
        # 按 name 去重，避免重复插入
        exists = db.query(Persona).filter(
            Persona.name == preset["name"],
            Persona.is_preset.is_(True),
        ).first()
        if exists:
            continue

        persona = Persona(
            user_id="",  # 预设人格不属于任何具体用户
            name=preset["name"],
            description=preset["description"],
            source_type="preset",
            source_content=None,
            parsed_prompt=json.dumps(preset["parsed_prompt"], ensure_ascii=False),
            is_preset=True,
        )
        db.add(persona)

    db.commit()
    logger.info(f"预设人格初始化完成，共 {len(_PRESETS)} 种。")
