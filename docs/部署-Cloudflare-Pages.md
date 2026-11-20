# 部署到 Cloudflare Pages（免费 · 免备案）

本项目是**纯静态站点**（`web/` 目录），不需要构建。Cloudflare Pages 免费、带宽不限、免备案，且能连 GitHub 自动部署。

---

## 一、首次设置（5 分钟）

1. 打开 <https://dash.cloudflare.com/sign-up> 注册 / 登录（免费）

2. 左侧菜单 → **Workers & Pages** → **Create** → 选 **Pages** → **Connect to Git**

3. 授权 GitHub，选择仓库 **`saviorbill/asset-cycle-atlas`**

4. 构建设置（关键）：

   | 项 | 值 |
   |---|---|
   | Project name | `asset-cycle-atlas` |
   | Production branch | `main` |
   | Framework preset | **None** |
   | Build command | **留空** |
   | Build output directory | **`web`** |

5. 点 **Save and Deploy**，等 1–2 分钟

6. 得到访问地址：`https://asset-cycle-atlas.pages.dev`

---

## 二、绑定自己的域名（可选，免备案）

1. 项目 → **Custom domains** → **Set up a custom domain**
2. 输入你的域名（如 `fupan.yourdomain.com`）
3. 按提示到域名服务商加一条 CNAME → `asset-cycle-atlas.pages.dev`
4. Cloudflare 自动签发 HTTPS

> 注意：域名用 Cloudflare 的**全球网络**（不含大陆节点），所以**不需要备案**；国内访问比 GitHub Pages 稳，但不是国内 CDN 那种速度。

---

## 三、以后如何更新

**什么都不用做** —— 保持现在的流程即可：

```bash
git add -A && git commit -m "xxx" && git push
```

Cloudflare Pages 会监听到 `main` 分支的 push，自动重新部署，约 1 分钟生效。

---

## 四、命令行部署（可选）

如果你不想用 Git 集成，也可以用 Wrangler 手动上传：

```bash
cd web
npx wrangler pages deploy . --project-name=asset-cycle-atlas
# 首次会要求浏览器登录 Cloudflare
```

---

## 五、已预置的优化

仓库里已放了 `web/_headers`，Cloudflare Pages 会自动应用：

- 全站：`X-Content-Type-Options: nosniff`、`X-Frame-Options: SAMEORIGIN`、`Referrer-Policy`
- `echarts.min.js` 与 `fonts/*`：长缓存（`immutable`，1 年）
- 其余资源：`must-revalidate`（数据更新后立即生效，不会读到旧数据）

---

## 六、和 GitHub Pages 的关系

- 两个可以**同时存在**，互不影响
- 建议：Cloudflare Pages 作为主站，GitHub Pages 保留作为备份/开源展示
- 如果要停用 GitHub Pages：仓库 Settings → Pages → 删除即可
