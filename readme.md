# 📊 投资组合管理 | Portfolio Manager

一个纯静态的投资组合管理网页，可部署在 GitHub Pages 上，支持 **A股、港股、美股、基金** 的行情查询与持仓管理。

## ✨ 功能特性

- **自动识别** — 输入股票/基金代码，自动检测市场并获取名称和最新价格
- **收益计算** — 输入成本价后，自动计算累计盈亏、累计收益率、今日盈亏
- **多市场支持** — A股（沪市/深市）、港股、美股、场外基金
- **投资分布图** — 按市场（A股/港股/美股/基金）和资产类型（股票/基金）生成饼图
- **分红管理** — 支持手动/自动记录现金分红和分红复投，A股支持自动检测分红公告
- **交易时段感知** — 今日盈亏根据各市场交易时段智能显示（周末/非交易时段为0，美股按中国时区显示）
- **手机端适配** — 响应式卡片布局，移动端自动切换为卡片视图
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

## ⚙️ 数据源说明

> 本页面使用**全免费、无需认证**的数据接口，开箱即用。

### 股票行情 — 腾讯财经（直连，无需代理）

使用腾讯财经 `qt.gtimg.cn` API，支持 A股、港股、美股批量查询：
- ✅ 无需任何配置
- ✅ 无跨域限制（CORS友好）
- ✅ 支持批量查询（最多50只/次）

### 基金行情 — 天天基金 JSONP（直连，无需代理）

使用天天基金 `fundgz.1234567.com.cn` API，通过 **JSONP（`<script>`标签注入）** 绕过浏览器跨域限制：
- ✅ 默认直连，无需代理，国内访问极快
- ⚠️ 极少数情况下 JSONP 加载失败时，自动回退到 CORS 代理

### CORS 代理配置（可选，仅作基金回退）

如果你希望有更强的容错能力，可以部署一个 Cloudflare Worker 代理：

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

### 分红管理

点击每个持仓的「分红」按钮，可以：
- **手动添加** — 记录现金分红或分红复投（复投将自动增加持股数量）
- **A股自动检测** — 点击「检测近期分红」自动查询东方财富分红公告
- **自动复投开关** — 开启后，检测到的分红将自动按市价复投（A股按100股手数取整）

### 今日盈亏显示规则

| 市场 | 交易日 | 非交易日 |
|------|--------|----------|
| A股/港股/基金 | 周一至周五 9:30起显示 | 周末全天为0 |
| 美股（中国时区） | 周一至周五显示，周一21:30前为0 | 周六显示周五盈亏，周日为0 |

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

### 数据管理

- **刷新行情** — 手动刷新所有持仓的最新价格（`Ctrl+R` 快捷键）
- **导出** — 将持仓数据导出为 JSON 文件备份
- **导入** — 从 JSON 文件恢复持仓数据
- **清空** — 删除所有持仓数据（需确认）
- **自动刷新** — 每10分钟自动刷新行情并检查分红

## 🏗️ 技术架构

| 组件 | 技术方案 | 说明 |
|------|----------|------|
| 股票行情 | [腾讯财经 qt.gtimg.cn](https://qt.gtimg.cn) | 免费、无需认证、CORS友好、GBK编码 |
| 基金行情 | [天天基金 1234567.com.cn](https://fundgz.1234567.com.cn) | 免费、JSONP直连、无需代理 |
| A股分红检测 | [东方财富 datacenter](https://datacenter-web.eastmoney.com) | 通过CORS代理访问 |
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

### JSONP 直连基金

为绕过跨域限制并加速国内访问，基金行情采用 JSONP 技术：

```javascript
// 动态创建 <script> 标签加载天天基金 JSONP 响应
// 无需代理，直连国内服务器，速度快
script.src = 'https://fundgz.1234567.com.cn/js/' + code + '.js';
```

仅在 JSONP 加载失败时回退到 Cloudflare Worker 代理。

## ⚠️ 注意事项

- 所有数据保存在**浏览器本地**（localStorage），清除浏览器数据会丢失持仓，建议定期导出备份
- 基金净值为**估值**，非实时价格，最终净值以基金公司公布为准
- 股票行情来源于腾讯财经，可能存在数秒至数十秒的延迟，仅供参考
- 港股代码请输入 4-5 位数字（如 `700` 或 `00700`），系统会自动补齐为 5 位
- 页面需在 **HTTPS** 环境下访问（GitHub Pages 默认支持），否则部分 API 可能因混合内容限制无法调用
- A股分红自动检测依赖东方财富 API，需要通过CORS代理访问。手动记录分红不受此限制

## 📄 许可

MIT License
