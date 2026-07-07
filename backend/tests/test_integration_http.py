"""联调测试脚本：通过 HTTP 接口测试所有功能。

测试项：
1. GET /health - 健康检查
2. POST /api/v1/chat/stream - SSE 流式对话（真实 LLM）
3. GET /api/v1/chat/history - 查询历史
4. DELETE /api/v1/chat/{thread_id} - 清空会话
5. GET /api/v1/personas - 人格列表
6. GET /api/v1/projects - 项目列表
"""
import asyncio
import json
import sys
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8001"
THREAD_ID = "integration-test-001"


async def test_health():
    """1. 健康检查。"""
    print("=" * 70)
    print("测试 1：GET /health")
    print("=" * 70)
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(f"{BASE}/health")
        print(f"状态码：{r.status_code}")
        print(f"响应：{r.json()}")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"
        print("[校验] ✅ 健康检查通过\n")


async def test_sse_stream():
    """2. SSE 流式对话（真实 LLM）。"""
    print("=" * 70)
    print(f"测试 2：POST /api/v1/chat/stream（thread_id={THREAD_ID}）")
    print("=" * 70)
    payload = {"message": "用一句话解释什么是 API", "thread_id": THREAD_ID}

    chunks = []
    async with httpx.AsyncClient(timeout=60) as c:
        async with c.stream("POST", f"{BASE}/api/v1/chat/stream", json=payload) as r:
            print(f"状态码：{r.status_code}")
            print(f"Content-Type：{r.headers.get('content-type')}")
            assert r.status_code == 200, f"期望 200，实际 {r.status_code}"

            # 解析 SSE 事件流
            event_type = None
            async for line in r.aiter_lines():
                if line.startswith("event:"):
                    event_type = line[6:].strip()
                elif line.startswith("data:"):
                    data = line[5:].strip()
                    if event_type == "token":
                        chunks.append(data)
                    elif event_type == "done":
                        print(f"[done] {data}")
                        break
                    elif event_type == "error":
                        print(f"[error] {data}")
                        break

    full_reply = "".join(chunks)
    print(f"\n[流式回复] 共 {len(chunks)} 个 chunk，{len(full_reply)} 字")
    print(f"[回复预览] {full_reply[:200]}...")

    assert len(chunks) > 0, "应有 token chunk"
    assert len(full_reply) > 0, "回复不应为空"
    print("[校验] ✅ SSE 流式对话通过\n")


async def test_history():
    """3. 查询会话历史。"""
    print("=" * 70)
    print(f"测试 3：GET /api/v1/chat/history（thread_id={THREAD_ID}）")
    print("=" * 70)
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(f"{BASE}/api/v1/chat/history", params={"thread_id": THREAD_ID})
        print(f"状态码：{r.status_code}")
        data = r.json()
        print(f"消息数：{data['count']}")
        for i, msg in enumerate(data["messages"]):
            content_preview = msg["content"][:60] if msg["content"] else ""
            print(f"  [{i}] role={msg['role']}, type={msg['type']}, content={content_preview}...")

        assert r.status_code == 200
        assert data["count"] >= 2, "至少应有 2 条消息（Human + AI）"
        print("[校验] ✅ 历史查询通过\n")


async def test_projects_crud():
    """4. 项目 CRUD 完整流程。"""
    print("=" * 70)
    print("测试 4：项目 CRUD（POST → GET → GET/{id} → PUT → DELETE）")
    print("=" * 70)
    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as c:
        # 4.1 创建项目
        create_payload = {
            "name": "联调测试项目",
            "description": "测试用，可删除",
        }
        r = await c.post(f"{BASE}/api/v1/projects/", json=create_payload)
        print(f"[创建] 状态码：{r.status_code}")
        assert r.status_code in (200, 201), f"创建失败：{r.text}"
        proj = r.json()
        proj_id = proj["id"]
        print(f"[创建] 项目 id={proj_id}, name={proj['name']}")

        # 4.2 列表
        r = await c.get(f"{BASE}/api/v1/projects/")
        print(f"[列表] 状态码：{r.status_code}, 项目数：{len(r.json())}")
        assert r.status_code == 200
        assert len(r.json()) >= 1

        # 4.3 查询
        r = await c.get(f"{BASE}/api/v1/projects/{proj_id}")
        print(f"[查询] 状态码：{r.status_code}")
        assert r.status_code == 200
        assert r.json()["id"] == proj_id

        # 4.4 更新
        r = await c.put(
            f"{BASE}/api/v1/projects/{proj_id}",
            json={"name": "联调测试项目-改"},
        )
        print(f"[更新] 状态码：{r.status_code}")
        assert r.status_code == 200
        assert r.json()["name"] == "联调测试项目-改"

        # 4.5 删除
        r = await c.delete(f"{BASE}/api/v1/projects/{proj_id}")
        print(f"[删除] 状态码：{r.status_code}")
        assert r.status_code in (200, 204)

        # 4.6 验证已删除
        r = await c.get(f"{BASE}/api/v1/projects/{proj_id}")
        print(f"[删除后查询] 状态码：{r.status_code}")
        assert r.status_code == 404

    print("[校验] ✅ 项目 CRUD 通过\n")


async def test_clear_session():
    """6. 清空会话。"""
    print("=" * 70)
    print(f"测试 6：DELETE /api/v1/chat/{THREAD_ID}")
    print("=" * 70)
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.delete(f"{BASE}/api/v1/chat/{THREAD_ID}")
        print(f"状态码：{r.status_code}")
        print(f"响应：{r.json()}")

        assert r.status_code == 200
        assert r.json()["success"] is True
        print("[校验] ✅ 清空会话通过\n")

    # 验证清空后历史为空
    print("[验证] 清空后查询历史...")
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(f"{BASE}/api/v1/chat/history", params={"thread_id": THREAD_ID})
        data = r.json()
        print(f"清空后消息数：{data['count']}")
        assert data["count"] == 0, "清空后历史应为空"
        print("[校验] ✅ 清空后历史为空\n")


async def main():
    print("=" * 70)
    print("AI 学习助手 · 联调测试开始")
    print("=" * 70)

    try:
        await test_health()
        await test_sse_stream()
        await test_history()
        await test_projects_crud()
        await test_clear_session()

        print("=" * 70)
        print("✅ 联调测试全部通过")
        print("=" * 70)
    except AssertionError as e:
        print(f"\n❌ 断言失败：{e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ 运行时错误：{type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
