# Product Marketing Context — 卫健委政策速查

*Last updated: 2026-05-29*

## Product Overview
**One-liner:** 微信小程序里随时查阅国家卫健委最新政策文件，AI 帮你摘要和分类。
**What it does:** 自动抓取国家卫健委官网发布的规范性文件和政策解读，用 DeepSeek AI 生成摘要和分类，用户在微信小程序内浏览、搜索、收藏。
**Product category:** 政策信息工具 / 医疗行业资讯
**Product type:** 微信小程序（工具类）
**Business model:** 免费工具，暂无变现（后续可考虑：机构定制版、专业版订阅、政策对比高级功能）

## Target Audience
**Target users:**
- 医疗行业从业者（医院管理者、卫生行政人员）——需要及时跟进政策变化
- 政策研究者（智库、高校、咨询公司）——需要系统查阅和追溯
- 基层医务工作者——需要了解最新行业规范和标准
**Primary use case:** 用手机随时搜到最新卫健委政策，不用打开电脑翻官网
**Jobs to be done:**
- "我在手机上快速找到最新政策并了解它说了什么"
- "我想知道某个领域（如妇幼健康）最近出了什么新规"
- "我听说有个新政策但记不清文件名，帮我搜到它"
**Use cases:**
- 医院管理者晨会前快速查看昨天发布的新政策
- 研究人员按分类浏览某一领域所有相关文件
- 基层医生遇到规范问题时搜索关键词找到对应文件

## Problems & Pain Points
**Core problem:** 卫健委官网不好用——没有移动端适配、搜索弱、文件多但没分类，只能 PC 端翻
**Why alternatives fall short:**
- 卫健委官网：无移动端、无摘要、难搜索
- 微信公众号：信息碎片化，不系统
- 百度搜索：结果混杂，权威性难判断
**What it costs them:** 每次查政策要打开电脑翻官网 10-20 分钟，移动场景下几乎不可能
**Emotional tension:** "政策出了但我不知道""同事都在讨论新规了我还没看过"——信息焦虑

## Competitive Landscape
**Direct:** 暂无直接竞品（微信小程序形式做卫健委政策聚合+AI 摘要的还未出现）
**Secondary:** 卫健委官网本身 —— 数据源权威但体验差
**Indirect:** 医疗行业公众号、今日头条医疗频道 —— 信息碎片化、不权威

## Differentiation
**Key differentiators:**
- 全自动爬虫+AI 摘要，无需人工维护
- 微信小程序即开即用，无需下载安装
- 8 大分类体系，比官网好找
**How we do it differently:** Playwright 无头浏览器绕过反爬 + DeepSeek 一次性完成分类摘要
**Why customers choose us:** 手机上搜政策比在电脑上翻官网快 10 倍

## Objections
| Objection | Response |
|-----------|----------|
| "数据权威吗？" | 数据源就是卫健委官网，原文链接可追溯，AI 只做摘要不篡改内容 |
| "会不会漏掉文件？" | 定时爬取+URL 去重，首次全量后续增量，覆盖规范性文件和政策解读两类 |
| "免费的以后会不会收费？" | 核心查询功能永久免费 |

**Anti-persona:** 有专业数据库的企业用户（已购买万方/知网等专业服务）

## Switching Dynamics
**Push:** 官网难用、无移动端、搜索弱
**Pull:** 微信小程序方便、AI 摘要省时间、分类清晰
**Habit:** 习惯在 PC 上搜索官网或问同事
**Anxiety:** 担心 AI 摘要不够准确、担心数据不全

## Customer Language
**How they describe the problem:**
- "那个卫健委的文件在哪儿查原文？"
- "这个新政策什么时候发的，说了什么？"
- "医疗这块最近有啥新规定？"
**How they describe us:** "手机上的卫健委政策速查工具"
**Words to use:** 权威、及时、全面、方便、速查、官方来源
**Words to avoid:** 替代卫健委、独家解读（避免暗示替代官方）
**Glossary:**
| Term | Meaning |
|------|---------|
| 规范性文件 | 卫健委发布的正式法规/规范文件 |
| 政策解读 | 卫健委对政策文件的官方解释说明 |
| NHC | 国家卫健委 (National Health Commission) |

## Brand Voice
**Tone:** 专业、客观、可信赖（不做主观解读，只做信息传递）
**Style:** 简洁直接，政务蓝配色
**Personality:** 可靠的、高效的、中立的

## Goals
**Business goal:** 成为医疗从业者查策的首选工具
**Conversion action:** 用户搜索政策 → 找到文件 → 收藏/分享 → 持续回访
**Current metrics:** 待上线，无数据
