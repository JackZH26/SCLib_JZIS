# SCLib Google OAuth 集成实施说明
> **For Claude Code** | Version: 1.0 | Date: 2026-04-16
> **Repo:** https://github.com/JackZH26/SCLib_JZIS
> **Credentials:** Already in `/opt/SCLib_JZIS/.env` on VPS2

---

## 前置确认

✅ Google OAuth Client ID: `YOUR_GOOGLE_CLIENT_ID.apps.googleusercontent.com`
✅ Google OAuth Client Secret: `GOCSPX-YOUR_GOOGLE_CLIENT_SECRET`
✅ 已写入 VPS2 `/opt/SCLib_JZIS/.env`
✅ 测试用户: jack@jzis.org, info@jzis.org
✅ Redirect URI: `https://api.jzis.org/v1/auth/google/callback`

---

## Phase 1: 数据库 Migration

### 创建 Alembic migration 文件

```python
# api/alembic/versions/0003_google_oauth.py
"""Add Google OAuth fields to users

Revision ID: 0003
Down revision: 0002
"""
from alembic import op
import sqlalchemy as sa

def upgrade():
    # Add Google OAuth fields
    op.add_column('users', sa.Column('google_sub', sa.String(128), unique=True, nullable=True))
    op.add_column('users', sa.Column('auth_provider', sa.String(20), server_default='local'))
    op.add_column('users', sa.Column('avatar_url', sa.String(500), nullable=True))

    # Allow password_hash to be null (Google users have no password)
    op.alter_column('users', 'password_hash', nullable=True)

    # Index for fast Google sub lookup
    op.create_index('idx_users_google_sub', 'users', ['google_sub'],
                    postgresql_where=sa.text("google_sub IS NOT NULL"))

def downgrade():
    op.drop_index('idx_users_google_sub', 'users')
    op.drop_column('users', 'avatar_url')
    op.drop_column('users', 'auth_provider')
    op.drop_column('users', 'google_sub')
```

**运行 migration:**
```bash
cd /opt/SCLib_JZIS
docker compose -f docker-compose.yml -f docker-compose.prod.yml \
  exec api alembic upgrade head
```

---

## Phase 2: 后端实现

### 2.1 添加依赖

```toml
# api/pyproject.toml — 在 dependencies 中追加
"authlib>=1.3",
"itsdangerous>=2.1",
"httpx>=0.27",
```

### 2.2 更新 config.py

```python
# api/config.py — 在 Settings 类中追加字段
google_client_id: str = Field(default="")
google_client_secret: str = Field(default="")
frontend_callback_url: str = Field(default="https://jzis.org/sclib/auth/callback")
```

### 2.3 更新 db.py (User model)

```python
# api/models/db.py — User 类中追加字段
google_sub: Mapped[Optional[str]] = mapped_column(String(128), unique=True, nullable=True)
auth_provider: Mapped[str] = mapped_column(String(20), default="local")
avatar_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

# 同时修改 password_hash 为可空
password_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
```

### 2.4 更新 main.py — 添加 Session 中间件

在 `app = FastAPI(...)` 之后添加（必须在 CORS 之前）：

```python
# api/main.py
from starlette.middleware.sessions import SessionMiddleware

# 在现有 middleware 之前添加（顺序重要）
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.jwt_secret,
    max_age=300,       # OAuth state 5分钟过期
    https_only=True,   # 生产环境强制 HTTPS
    same_site="lax",
)
```

### 2.5 创建 OAuth 服务文件

```python
# api/services/google_oauth.py
"""Google OAuth2 service using authlib."""
from __future__ import annotations

from authlib.integrations.starlette_client import OAuth

from api.config import get_settings

settings = get_settings()

oauth = OAuth()
oauth.register(
    name="google",
    client_id=settings.google_client_id,
    client_secret=settings.google_client_secret,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={
        "scope": "openid email profile",
        "prompt": "select_account",  # 每次显示账号选择器
    },
)
```

### 2.6 在 auth.py router 中添加 Google 端点

```python
# api/routers/auth.py — 在文件末尾追加

from starlette.requests import Request
from starlette.responses import RedirectResponse
from sqlalchemy import select, or_
from api.services.google_oauth import oauth
from api.models.db import User

@router.get("/google/login", tags=["auth"])
async def google_login(request: Request):
    """Redirect to Google OAuth consent screen."""
    redirect_uri = str(request.url_for("google_callback"))
    return await oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/google/callback", name="google_callback", tags=["auth"])
async def google_callback(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Handle Google OAuth callback: upsert user, issue JWT, redirect to frontend."""
    settings = get_settings()

    try:
        token = await oauth.google.authorize_access_token(request)
    except Exception as e:
        # OAuth error (state mismatch, user denied, etc.)
        return RedirectResponse(
            url=f"{settings.frontend_callback_url}?error=oauth_failed&detail={str(e)[:100]}",
            status_code=302,
        )

    userinfo = token.get("userinfo", {})
    google_sub = userinfo.get("sub")
    email = userinfo.get("email")

    if not google_sub or not email:
        return RedirectResponse(
            url=f"{settings.frontend_callback_url}?error=missing_userinfo",
            status_code=302,
        )

    # Upsert: find by google_sub OR email
    stmt = select(User).where(
        or_(User.google_sub == google_sub, User.email == email)
    )
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if user is None:
        # New user — create with Google info
        user = User(
            email=email,
            name=userinfo.get("name") or email.split("@")[0],
            google_sub=google_sub,
            auth_provider="google",
            avatar_url=userinfo.get("picture"),
            email_verified=True,
            is_active=True,
            password_hash=None,  # No password for Google users
        )
        db.add(user)
    else:
        # Existing user — bind Google account
        if not user.google_sub:
            user.google_sub = google_sub
        if userinfo.get("picture") and not user.avatar_url:
            user.avatar_url = userinfo.get("picture")
        if user.auth_provider == "local":
            user.auth_provider = "both"
        # Ensure user is active
        user.email_verified = True
        user.is_active = True

    await db.commit()
    await db.refresh(user)

    # Issue JZIS JWT
    jwt_token = create_access_token({"sub": str(user.id), "email": user.email})

    # Redirect to frontend with token
    return RedirectResponse(
        url=f"{settings.frontend_callback_url}?token={jwt_token}",
        status_code=302,
    )
```

### 2.7 注册 OAuth router（确保 /v1/auth/google/callback URL 可用）

在 main.py 中确认路由前缀包含完整路径：

```python
# api/main.py — 路由注册部分
# 确保 auth router 挂载在 /v1/auth
app.include_router(auth_router, prefix="/v1/auth", tags=["auth"])
```

---

## Phase 3: 前端实现

### 3.1 新建 OAuth 回调页

```tsx
// frontend/app/auth/callback/page.tsx
"use client"

import { useEffect, useState } from "react"
import { useRouter, useSearchParams } from "next/navigation"

export default function AuthCallbackPage() {
  const router = useRouter()
  const params = useSearchParams()
  const [status, setStatus] = useState<"loading" | "error">("loading")
  const [errorMsg, setErrorMsg] = useState("")

  useEffect(() => {
    const token = params.get("token")
    const error = params.get("error")

    if (error) {
      setStatus("error")
      setErrorMsg(
        error === "oauth_failed" ? "Google sign-in failed. Please try again." :
        error === "missing_userinfo" ? "Could not retrieve account info from Google." :
        "An error occurred during sign-in."
      )
      return
    }

    if (token) {
      // Store JWT — use same key as the rest of the app
      localStorage.setItem("sclib_token", token)
      // Redirect to home or intended destination
      const next = sessionStorage.getItem("auth_redirect") || "/sclib"
      sessionStorage.removeItem("auth_redirect")
      router.replace(next)
    } else {
      setStatus("error")
      setErrorMsg("No token received. Please try again.")
    }
  }, [params, router])

  if (status === "error") {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-center">
          <p className="text-red-600 mb-4">{errorMsg}</p>
          <a href="/sclib/auth/login" className="text-blue-600 underline">
            Back to login
          </a>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen flex items-center justify-center">
      <div className="text-center">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600 mx-auto mb-4" />
        <p className="text-gray-600">Signing you in...</p>
      </div>
    </div>
  )
}
```

### 3.2 登录页添加 Google 按钮

```tsx
// frontend/app/auth/login/page.tsx — 在邮箱表单之前插入

const GOOGLE_LOGIN_URL = `${process.env.NEXT_PUBLIC_API_BASE}/auth/google/login`

// 在 return 中，表单之前添加：
<div className="mb-6">
  <a
    href={GOOGLE_LOGIN_URL}
    className="w-full flex items-center justify-center gap-3 px-4 py-2.5 border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors"
  >
    {/* Google SVG icon */}
    <svg viewBox="0 0 24 24" className="w-5 h-5" xmlns="http://www.w3.org/2000/svg">
      <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4"/>
      <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/>
      <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" fill="#FBBC05"/>
      <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335"/>
    </svg>
    <span className="text-sm font-medium text-gray-700">Continue with Google</span>
  </a>
</div>

<div className="relative mb-6">
  <div className="absolute inset-0 flex items-center">
    <div className="w-full border-t border-gray-200" />
  </div>
  <div className="relative flex justify-center text-xs text-gray-500">
    <span className="bg-white px-2">or sign in with email</span>
  </div>
</div>
```

### 3.3 注册页添加 Google 按钮

与登录页相同的 Google 按钮代码，添加到注册表单之前，文案改为：

```
"Sign up with Google"
```

---

## Phase 4: 修复 "Failed to fetch" 错误处理

这是与 Google OAuth 无关但同样需要修复的 bug：

```typescript
// frontend/lib/api.ts — 替换 request 函数

async function request<T>(
  path: string,
  init: RequestInit & { auth?: string; apiKey?: string } = {}
): Promise<T> {
  const headers = new Headers(init.headers)
  headers.set("Content-Type", "application/json")
  if (init.auth) headers.set("Authorization", `Bearer ${init.auth}`)
  if (init.apiKey) headers.set("X-API-Key", init.apiKey)

  let res: Response
  try {
    res = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers,
      cache: "no-store",
    })
  } catch {
    // True network failure (no connection, DNS failure, etc.)
    throw new ApiError(0, { detail: "Network error: unable to reach server" })
  }

  if (res.ok) {
    // 204 No Content
    if (res.status === 204) return undefined as T
    return res.json() as Promise<T>
  }

  // Parse error body
  let body: { detail?: string } = {}
  try {
    body = await res.json()
  } catch {
    body = { detail: res.statusText }
  }

  const err = new ApiError(res.status, body)

  // User-friendly messages by status code
  switch (res.status) {
    case 401:
      err.message = body.detail || "Invalid email or password"
      break
    case 403:
      err.message = "You do not have permission to perform this action"
      break
    case 422:
      err.message = body.detail || "Invalid input. Please check your details."
      break
    case 429:
      err.message = "Daily free query limit reached. Please sign in for unlimited access."
      break
    case 503:
      err.message = "Service temporarily unavailable. Please try again."
      break
    default:
      err.message = body.detail || `Error ${res.status}`
  }

  throw err
}
```

---

## Phase 5: Nginx 配置更新（VPS2）

确保 `api.jzis.org` 的 nginx server block 包含 session cookie 所需的配置：

```nginx
# /etc/nginx/sites-available/jzis.org — api.jzis.org server block 中追加
# 在现有 location / 块之前添加：

# Google OAuth callback — 需要正确传递 cookie
location /v1/auth/google/ {
    proxy_pass http://127.0.0.1:8000/v1/auth/google/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    # 重要：传递 Cookie（OAuth state 存在 session cookie 里）
    proxy_set_header Cookie $http_cookie;
    proxy_pass_header Set-Cookie;
}
```

**更新后 reload nginx：**
```bash
nginx -t && systemctl reload nginx
```

---

## Phase 6: 构建 & 部署

```bash
cd /opt/SCLib_JZIS

# 1. 拉取最新代码
git pull origin main

# 2. 运行数据库 migration
docker compose -f docker-compose.yml -f docker-compose.prod.yml \
  exec api alembic upgrade head

# 3. 重新构建 API 容器（新增 authlib 依赖）
docker compose -f docker-compose.yml -f docker-compose.prod.yml \
  build --no-cache api

# 4. 重新构建前端（新增 Google 按钮和回调页）
docker compose -f docker-compose.yml -f docker-compose.prod.yml \
  build --no-cache frontend

# 5. 重启所有容器
docker compose -f docker-compose.yml -f docker-compose.prod.yml \
  up -d api frontend

# 6. 验证 API 启动
docker compose logs api --tail 20

# 7. Reload nginx
nginx -t && systemctl reload nginx
```

---

## Phase 7: 验证测试

```bash
# 7.1 确认 Google OAuth 端点存在
curl -sk https://api.jzis.org/v1/auth/google/login -I | grep "HTTP\|Location"
# 预期: HTTP/1.1 302 Found, Location: accounts.google.com/...

# 7.2 确认回调页面存在
curl -sk https://jzis.org/sclib/auth/callback -o /dev/null -w "%{http_code}"
# 预期: 200

# 7.3 用浏览器测试完整流程
# 打开: https://jzis.org/sclib/auth/login
# 点击 "Continue with Google"
# 用 jack@jzis.org 或 info@jzis.org 登录（测试用户）
# 授权后应跳转回 jzis.org/sclib 并显示已登录状态
```

---

## 注意事项

1. **测试模式限制**：当前 Google OAuth 只有添加的测试用户才能使用（jack@jzis.org, info@jzis.org）。面向所有用户开放需要在 Google Cloud Console 提交"发布应用"审核（通常需要 1-3 天）。

2. **Session 中间件顺序**：`SessionMiddleware` 必须在 `CORSMiddleware` 之前注册，否则 OAuth state 会丢失。

3. **HTTPS 必需**：`SessionMiddleware` 的 `https_only=True` 在生产环境中是必须的，本地开发时需改为 `False`。

4. **密码可空**：Google 用户的 `password_hash` 为 NULL，注意登录逻辑中要处理这种情况（不要在 NULL 密码上做 bcrypt 比较）。

5. **账号合并**：同一 email 的本地账号和 Google 账号会自动合并，`auth_provider` 设为 `"both"`。

---

*SCLib Google OAuth Implementation Guide | 瓦力 | 2026-04-16*
