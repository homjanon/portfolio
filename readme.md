# 📊 投资组合管理 | Portfolio Manager

一个纯静态的投资组合管理网页，可部署在 GitHub Pages 上，支持 **A股、港股、美股、基金** 的行情查询与持仓管理。

## ✨ 功能特性

- **自动识别** — 输入股票/基金代码，自动检测市场并获取名称和最新价格
- **收益计算** — 输入成本价后，自动计算累计盈亏、累计收益率、今日盈亏
- **多市场支持** — A股（沪市/深市）、港股、美股、场外基金
- **投资分布图** — 按市场（A股/港股/美股/基金）和资产类型（股票/ETF/基金）生成饼图
- **数据持久化** — 所有持仓数据保存在浏览器 localStorage，刷新不丢失
- **导入/导出** — 支持 JSON 格式导入导出，方便备份和迁移
- **零后端依赖** — 纯静态 HTML 文件，无需服务器

## 🚀 部署到 GitHub Pages

### 方法一：直接上传（最简单）

1. 在 GitHub 上创建一个新仓库，例如 `portfolio`
2. 将 `index.html` 上传到仓库根目录
3. 进入仓库 **Settings → Pages**
4. Source 选择 `Deploy from a branch`，Branch 选择 `main`，目录选 `/ (root)`
5. 点击 Save，等待 1-2 分钟即可访问

部署后访问地址：`https://<你的用户名>.github.io/portfolio/`

### 方法二：Git 命令行推送

```bash
# 创建仓库目录
mkdir portfolio && cd portfolio
git init

# 复制 index.html 到此目录
cp /path/to/index.html .

# 提交并推送
git add index.html
git commit -m "feat: 初始化投资组合管理页面"
git branch -M main
git remote add origin https://github.com/<你的用户名>/portfolio.git
git push -u origin main
```

然后在 GitHub 仓库 Settings → Pages 中启用即可。

## ⚙️ 基金数据配置（可选）

> 股票行情（A股/港股/美股）使用腾讯财经 API，**无需任何配置**即可使用。
> 基金行情使用天天基金 API，由于浏览器跨域限制，**需要配置 CORS 代理**。

### 部署 Cloudflare Worker 代理（推荐）

1. 注册 [Cloudflare](https://dash.cloudflare.com/) 账号（免费）
2. 进入 **Workers & Pages → Create**
3. 粘贴以下代码：

```javascript
export default {
  async fetch(request) {
    const url = new URL(request.url);
    const target = url.searchParams.get('url');
    if (!target) return new Response('Missing ?url=', { status: 400 });
    const resp = await fetch(target);
    const headers = new Headers(resp.headers);
    headers.set('Access-Control-Allow-Origin', '*');
    return new Response(resp.body, { status: resp.status, headers });
  }
};
```

4. 部署后获得 Worker URL，形如：`https://portfolio-proxy.<你的子域名>.workers.dev/`
5. 在页面上点击 **⚙️ 设置**，将 Worker URL 填入「CORS 代理地址」输入框，点击保存

> Cloudflare Workers 免费版每天支持 10 万次请求，个人使用完全足够。

### 公共代理备选

如果不想部署 Worker，页面的设置面板中也内置了公共代理备选：

- `https://corsproxy.io/?`
- `https://api.allorigins.win/raw?url=`

> ⚠️ 公共代理可能不稳定或有限流，推荐部署自己的 Cloudflare Worker。

## 📖 使用说明

### 添加持仓

| 字段 | 说明 | 示例 |
|------|------|------|
| 代码 | 股票或基金代码 | `600036`、`00700`、`INTC`、`001234` |
| 市场 | 可自动检测，也可手动选择 | A股沪市/深市、港股、美股、基金 |
| 持有数量 | 持有的股数或基金份额 | `100` |
| 成本价 | 买入单价 | `35.50` |

**自动检测规则：**
- 6位数字开头为 6 → 沪市（如 `600036`）
- 6位数字开头为 0 或 3 → 深市（如 `000001`、`300750`）
- 4-5位纯数字 → 港股（如 `00700`、`09988`）
- 含英文字母 → 美股（如 `INTC`、`QQQ`）
- 需要添加基金时，请手动选择「基金」市场

### 数据管理

- **导出** — 将持仓数据导出为 JSON 文件备份
- **导入** — 从 JSON 文件恢复持仓数据
- **清空** — 删除所有持仓数据（需确认）
- **刷新行情** — 手动刷新所有持仓的最新价格

### 代码输入示例

| 市场 | 输入代码 | 说明 |
|------|----------|------|
| A股沪市 | `600036` | 招商银行 |
| A股深市 | `000001` | 平安银行 |
| A股深市 | `300750` | 宁德时代 |
| 港股 | `00700` | 腾讯控股 |
| 港股 | `09988` | 阿里巴巴 |
| 美股 | `INTC` | Intel Corporation |
| 美股 | `QQQ` | Invesco QQQ Trust |
| 美股 | `VOO` | Vanguard S&P 500 ETF |
| 基金 | `001234` | 需手动选择「基金」市场 |

## 🏗️ 技术架构

| 组件 | 技术方案 | 说明 |
|------|----------|------|
| 股票行情 | [腾讯财经 qt.gtimg.cn](https://qt.gtimg.cn) | 免费、无需认证、支持跨域、GBK编码 |
| 基金行情 | [天天基金 1234567.com.cn](https://fundgz.1234567.com.cn) | 免费、返回JSONP、需CORS代理 |
| 图表 | [Chart.js](https://www.chartjs.org/) | CDN 引入，环形饼图 |
| 数据存储 | localStorage | 浏览器本地持久化 |
| 部署 | GitHub Pages | 零成本静态托管 |

### 编码处理

腾讯财经 API 返回 **GBK 编码**数据，浏览器默认以 UTF-8 解码会导致中文乱码。本页面通过以下方式处理：

```javascript
// 以 ArrayBuffer 方式读取响应，然后用 TextDecoder 手动 GBK 解码
const buffer = await resp.arrayBuffer();
const text = new TextDecoder('gbk').decode(buffer);
```

## ⚠️ 注意事项

- 所有数据保存在**浏览器本地**（localStorage），清除浏览器数据会丢失持仓，建议定期导出备份
- 基金净值为**估值**，非实时价格，最终净值以基金公司公布为准
- 股票行情来源于腾讯财经，可能存在数秒至数十秒的延迟，仅供参考
- 港股代码请输入 4-5 位数字（如 `700` 或 `00700`），系统会自动补齐为 5 位
- 页面需在 **HTTPS** 环境下访问（GitHub Pages 默认支持），否则部分 API 可能因混合内容限制无法调用

## 📄 许可

MIT License
