# 部署到 Gitee Pages（长期免费 · 国内节点 · 免备案）

Gitee Pages 是**长期免费**的国内静态托管：国内访问快、不需要 VPN、不需要域名、不需要备案。
代价：需要**实名认证**，且仓库必须**公开**。

---

## 一、准备（一次性）

### 1. 实名认证
登录 <https://gitee.com> → 头像 → **设置** → **实名认证**（身份证，通常几小时~1 个工作日）

### 2. 在 Gitee 创建仓库
- 新建仓库 → 名称：`asset-cycle-atlas`
- **公开**（Gitee Pages 免费版要求公开）
- **不要**勾选初始化 README

---

## 二、推送代码

在项目根目录执行（把 `你的Gitee用户名` 换成实际用户名）：

```bash
# 1) 推送源码（main 分支）
git remote add gitee https://gitee.com/你的Gitee用户名/asset-cycle-atlas.git
git push gitee main

# 2) 发布网站（自动把 web/ 内容推到 pages 分支）
./deploy-gitee.sh 你的Gitee用户名 asset-cycle-atlas
```

---

## 三、开启 Pages（首次）

1. 打开 `https://gitee.com/你的用户名/asset-cycle-atlas/pages`
2. **部署分支** 选 **`pages`**
3. 点 **启动服务**

完成后访问：

```
https://你的用户名.gitee.io/asset-cycle-atlas/
```

> 国内直接打开，速度很快。

---

## 四、以后如何更新

```bash
git push gitee main
./deploy-gitee.sh 你的Gitee用户名 asset-cycle-atlas
```

然后在 Gitee Pages 页面点 **「更新」**（免费版不会自动部署，需要手动点一次）。

---

## 五、注意事项

| 项 | 说明 |
|---|---|
| 实名认证 | 必须，否则无法开通 Pages |
| 仓库公开 | 必须（免费版） |
| 自动部署 | ❌ 免费版不支持，每次更新需手动点「更新」 |
| HTTPS | 免费版默认提供 Gitee 的 HTTPS 域名 |
| 自定义域名 | 免费版不支持（需 Pro） |
| 大小限制 | 单仓库/Pages 有容量限制，本项目约 13MB 没问题 |

---

## 六、与其他方案的对比

| 方案 | 长期免费 | 实名 | 国内无 VPN | 速度 | 自动部署 |
|---|---|---|---|---|---|
| **Gitee Pages** | ✅ | 需要 | ✅ | 快 | ❌ 手动点更新 |
| GitHub Pages（现用） | ✅ | 不需要 | ✅ | 慢（~6s） | ✅ |
| 腾讯云 CloudBase | ❌ 仅 6 个月 | 需要 | ✅ | 快 | 手动 |
| Cloudflare Pages | ✅ | 不需要 | ❌ pages.dev 被墙 | — | ✅ |
| 七牛云 | ⚠️ 测试域名 30 天回收 | 需要 | ✅ | 快 | — |

> 结论：**要"长期免费 + 国内快 + 不买域名"，Gitee Pages 是唯一选择**；如果不想实名，就继续用 GitHub Pages（能访问，只是慢）。
