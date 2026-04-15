# JZIS 统一账号体系方案
> **Version:** 1.0 | **Date:** 2026-04-15
> **作者:** 瓦力 | **状态:** 待 Claude Code 实施

---

## 一、现状分析

### 三个 JZIS 产品的账号现状

| 产品 | 域名 | 当前账号体系 | 问题 |
|------|------|------------|------|
| **jzis.org** | jzis.org | 无（纯静态页面） | 无账号 |
| **ASRP** | asrp.jzis.org | 无（桌面 App + 静态页） | 桌面 App 有 License Key 机制，但无 Web 账号 |
| **SCLib** | jzis.org/sclib | 独立账号系统（PostgreSQL + JWT） | 与其他产品完全隔离 |

**核心问题：**
- 用户在 SCLib 注册的账号，无法用于 ASRP 或其他未来 JZIS 产品
- 未来每增加一个产品，就需要新的账号系统
- 用户体验碎片化

---

## 二、目标架构

**设计原则：**
- 一个邮箱 = 一个 JZIS 账号，通行所有产品
- 低改动成本——不引入重量级 IdP（如 Keycloak）
- 基于现有 SCLib 数据库和 JWT 方案扩展

**选择方案：SCLib Auth 作为中央认证服务**

不需要新建独立 Auth Server，直接把 SCLib 的 `users` 表升级为 **JZIS 统一用户表**，为每个产品颁发相同签名的 JWT。

```
用户
  ↓ 登录
api.jzis.org/auth/login     ← 统一认证端点
  ↓ 返回 JWT（含 scope）
浏览器存储 JWT
  ↓ 携带 JWT 访问
jzis.org/sclib/...          ← SCLib（scope: sclib）
asrp.jzis.org/...           ← ASRP Web（scope: asrp）
jzis.org/...                ← 主站（scope: basic）
```

---

## 三、数据库变更

### 3.1 users 表新增字段

```sql
ALTER TABLE users
  ADD COLUMN scopes TEXT[] DEFAULT ARRAY['basic'],
  -- 记录用户有权访问哪些产品
  -- 'basic' = 基础账号
  -- 'sclib' = SCLib 搜索权限
  -- 'asrp' = ASRP 下载权限（未来）
  
  ADD COLUMN sclib_api_key_count INTEGER DEFAULT 0,
  -- SCLib API Key 数量（现有字段关联）
  
  ADD COLUMN profile JSONB DEFAULT '{}';
  -- 可扩展的产品特定 profile 信息
  -- {"asrp": {"plan": "free", "downloads": 0}, "sclib": {...}}
```

### 3.2 JWT Payload 变更

当前 JWT（SCLib 独有）：
```json
{"sub": "user_id", "exp": 1234567890}
```

新统一 JWT：
```json
{
  "sub": "user_id",
  "email": "info@jzis.org",
  "name": "Jian Zhou",
  "scopes": ["basic", "sclib"],
  "iss": "jzis.org",
  "exp": 1234567890
}
```

---

## 四、API 端点重构

### 4.1 统一认证端点迁移

**当前：** `api.jzis.org/sclib/v1/auth/*`

**目标：** `api.jzis.org/v1/auth/*`（去掉 `/sclib/` 前缀）

| 端点 | 当前路径 | 新路径 | 说明 |
|------|---------|--------|------|
| 注册 | /sclib/v1/auth/register | /v1/auth/register | 统一注册 |
| 登录 | /sclib/v1/auth/login | /v1/auth/login | 返回统一 JWT |
| 验证邮件 | /sclib/v1/auth/verify | /v1/auth/verify | — |
| 获取当前用户 | /sclib/v1/auth/me | /v1/auth/me | — |
| 管理 API Key | /sclib/v1/auth/keys | /v1/auth/keys | SCLib 专属 |

**向后兼容：** 保留 `/sclib/v1/auth/*` 路由，内部代理到 `/v1/auth/*`

### 4.2 CORS 扩展

```python
# api/main.py
allow_origins = [
    "https://jzis.org",
    "https://www.jzis.org",
    "https://asrp.jzis.org",
    # 未来新产品追加到这里
]
```

---

## 五、前端变更

### 5.1 SCLib 前端

**auth/login/page.tsx** 改为调用 `/v1/auth/login`（无 `/sclib/` 前缀）

或者保持 `/sclib/v1/auth/login`（nginx 代理）——最小改动方案。

**关键 Bug 修复（立即执行）：**

```typescript
// frontend/lib/api.ts — 当前错误处理
async function request<T>(path: string, init = {}) {
  try {
    const res = await fetch(`${API_BASE}${path}`, {...init})
    // BUG: 对非2xx也显示 "Failed to fetch"
    if (!res.ok) {
      const body = await res.json().catch(() => ({}))
      throw new ApiError(res.status, body)
    }
    return res.json() as T
  } catch (e) {
    // 这里 catch 了所有错误，包括 ApiError
    // 导致 401/429 都显示 "Failed to fetch"
    throw new Error("Failed to fetch")  // ← 这行是 bug 根源
  }
}

// 修复后：
async function request<T>(path: string, init = {}) {
  let res: Response
  try {
    res = await fetch(`${API_BASE}${path}`, {...init})
  } catch (e) {
    // 只有真正的网络错误才到这里
    throw new Error("Network error: unable to reach server")
  }
  
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    const err = new ApiError(res.status, body)
    
    // 给各状态码友好提示
    if (res.status === 401) err.message = body.detail || "Invalid email or password"
    if (res.status === 429) err.message = "Daily query limit reached. Please sign in for unlimited access."
    if (res.status === 422) err.message = "Invalid input. Please check your details."
    if (res.status >= 500) err.message = "Server error. Please try again later."
    
    throw err
  }
  return res.json() as T
}
```

### 5.2 jzis.org 主站（未来）

在主站导航加"Sign In"按钮 → 跳转到 SCLib 登录页（统一登录入口）

### 5.3 ASRP 网站（asrp.jzis.org）

当前 ASRP 网站是纯静态，无需账号。未来若需要：
- 下载量统计 → 加 JZIS 账号登录
- License 管理 → 与 JZIS 账号绑定

---

## 六、实施步骤（给 Claude Code）

### Phase 1：立即（今日）
```
1. 修复 frontend/lib/api.ts 的错误处理 bug（见上方代码）
2. 给前端所有错误状态加友好提示
3. 把 429 错误显示为"今日免费次数已用完，请登录"而非"Failed to fetch"
4. 把 401 显示为"邮箱或密码错误"
```

### Phase 2：短期（本周）
```
1. users 表 ALTER TABLE 加 scopes 和 profile 字段
2. JWT payload 加入 scopes、iss 字段
3. CORS 允许列表加入 asrp.jzis.org
4. auth 端点在 nginx 层新增 /v1/auth/* 路由（不带 /sclib 前缀）
   → 这样 api.jzis.org/v1/auth/login 也可用
5. 注册页把 SCLib 改为 JZIS 品牌（"Create your JZIS account"）
6. 欢迎邮件改为 JZIS 口吻，提到"此账号通行所有 JZIS 产品"
```

### Phase 3：中期（未来）
```
1. jzis.org 主站加入导航登录按钮 → 跳转 SCLib 登录
2. ASRP 桌面 App 若需要账号系统 → 调用同一 auth API
3. 新增产品 → 在 scopes 加一个新 scope，注册时可选勾选
```

---

## 七、Nginx 配置新增（VPS2）

```nginx
# 新增：统一 auth 端点（无 /sclib/ 前缀）
# 添加到 api.jzis.org server block

location /v1/auth/ {
    proxy_pass http://127.0.0.1:8000/v1/auth/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

---

## 八、注册页优化

注册页标题和说明文案：

```
Create your JZIS Account

One account for all JZIS products:
- SCLib: Superconductivity research database
- ASRP: AI-powered scientific research platform  
- More coming soon

[Registration form fields...]
```

---

## 九、当前账号状态

**已创建（2026-04-15）：**
- Email: `info@jzis.org`
- Password: `Jzis@2026!`（请在登录后修改）
- Status: Active + Email verified ✅
- Scopes: basic, sclib

**临时密码需要修改** → 建议在 `/sclib/auth/dashboard` 修改。

---

## 十、总结

| 改动 | 成本 | 优先级 |
|------|------|--------|
| 修复 "Failed to fetch" bug | 30分钟 | P0 立即 |
| 429 友好提示 | 15分钟 | P0 立即 |
| scopes 字段 + JWT 更新 | 2小时 | P1 本周 |
| 统一 /v1/auth/ nginx 路由 | 15分钟 | P1 本周 |
| 注册页品牌升级 | 1小时 | P2 |

*JZIS Unified Auth Plan v1.0 | 瓦力 | 2026-04-15*
