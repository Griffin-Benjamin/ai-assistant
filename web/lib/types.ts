/**
 * 后端数据模型 TypeScript 类型定义
 *
 * 对应后端核心数据结构，供前端 API 调用与组件渲染使用。
 */

/** 学习项目 */
export interface LearningProject {
  id: string;
  name: string;
  description?: string;
  subject?: string;
  /** 用户自定义学习规则 ID（费曼/SQ3R/错题三刷等模板） */
  learningRuleId?: string;
  /** 接入的模型标识（deepseek / openai / claude 等） */
  modelProvider?: string;
  createdAt: string;
  updatedAt: string;
}

/** 知识树节点 */
export interface KnowledgeNode {
  id: string;
  projectId: string;
  parentId?: string | null;
  title: string;
  description?: string;
  /** 节点类型：学科 / 章节 / 知识点 / 错题等 */
  type: string;
  /** 掌握度 0-1 */
  mastery?: number;
  order?: number;
  createdAt: string;
  updatedAt: string;
}

/** 用户人格（语言风格 + 思考逻辑样本） */
export interface Persona {
  id: string;
  projectId: string;
  /** 表层语言风格样本（短语、句式、口头禅） */
  styleSamples: string[];
  /** 底层思考逻辑样本（拆解角度、关联习惯、易错倾向） */
  thinkingSamples: string[];
  /** 置信度 0-1，越高表示风格画像越稳定 */
  confidence: number;
  lastUpdatedAt: string;
  createdAt: string;
}

/** 定时任务（汇总 / 复习提醒等） */
export interface ScheduledTask {
  id: string;
  projectId: string;
  /** 任务类型：summarize / review / extract_style 等 */
  type: string;
  /** cron 表达式或自然语言描述 */
  schedule: string;
  /** 任务状态：pending / running / done / failed */
  status: string;
  /** 上次执行时间 */
  lastRunAt?: string;
  /** 下次执行时间 */
  nextRunAt?: string;
  createdAt: string;
  updatedAt: string;
}

/** 知识库条目（客观知识点：错题、笔记、心得） */
export interface KnowledgeItem {
  id: string;
  projectId: string;
  /** 所属知识树节点（可选） */
  nodeId?: string;
  /** 条目类型：note / mistake / insight */
  type: string;
  title: string;
  content: string;
  /** 学科标签 */
  subject?: string;
  /** 自定义标签 */
  tags?: string[];
  /** 来源：chat / manual / import */
  source?: string;
  /** 掌握状态：new / learning / mastered */
  masteryStatus?: string;
  createdAt: string;
  updatedAt: string;
}
