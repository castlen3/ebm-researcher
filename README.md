# EBM Researcher

**實證醫學文獻搜尋與綜合技能** — 讓 AI agent 自動執行 PubMed 臨床文獻搜尋，用 PICO 框架拆解問題、紀律性篩選證據、產出結構化繁中報告。

## 一句話說清楚

**你用自然語言問醫學問題，它幫你轉換成 PubMed 標準搜尋格式，自動查文獻、篩選證據、寫出結構化報告。**

不需要懂 PICO 怎麼寫、不需要會 PubMed 語法、不需要自己判斷哪篇論文比較可靠。你只要像平常問問題一樣說：

> 「補充生物素（biotin）能不能改善掉髮？」

它就會自動拆解成標準醫學問題、去 PubMed 搜、篩選高品質研究、最後用繁體中文告訴你答案和限制。

## 為什麼需要這個

一般 LLM 回答醫學問題，靠的是訓練資料裡的記憶，沒有真正去查文獻。這會有幾個問題：

- 資訊可能過時（訓練資料有截止日）
- 無法區分證據等級（一篇 case report 跟一篇 meta-analysis 被同等對待）
- 可能 hallucinate 出不存在的研究

EBM Researcher 解決這個問題。它讓 AI agent：

1. **自動拆解臨床問題** → PICO（Patient / Intervention / Comparison / Outcome）
2. **跑 PubMed 搜尋** → esearch → esummary → efetch 三階段管線
3. **紀律性篩選** → 不是找到論文就算數，要通過 Directness Gate
4. **停損機制** → 三輪放寬搜尋仍找不到就如實報告，不瞎湊答案
5. **結構化輸出** → 繁體中文報告，附 PubMed 連結，證據與推論分離

## 核心概念

### PICO 框架

把模糊的醫學問題拆成四個元素：

| 元素 | 說明 | 範例 |
|------|------|------|
| **P** (Patient/Population) | 什麼族群？ | 第二型糖尿病患者 |
| **I** (Intervention) | 什麼介入/治療？ | SGLT2 抑制劑 |
| **C** (Comparison) | 跟什麼比？ | placebo / 其他降血糖藥 |
| **O** (Outcome) | 看什麼結果？ | 心血管事件、死亡率 |

### 證據等級

搜尋結果按研究設計分級，優先納入高品質證據：

```
5 ─ Systematic Review / Meta-Analysis  ← 最高
4 ─ Randomized Controlled Trial (RCT)
3 ─ Cohort / Case-Control / Observational
2 ─ 一般臨床相關（標題含 patient/therapy 等）
1 ─ Case Report / Editorial / Letter   ← 最低
```

評分機制優先使用 PubMed 的 `PublicationType` 欄位（最可靠），退而用標題關鍵字匹配。頂級期刊（NEJM、Lancet、JAMA 等）額外 +1 分。

### Directness Gate（直接性閘門）

**找到論文 ≠ 找到答案。**

每篇搜尋到的論文必須通過 Directness Gate：

- ✅ **族群 (P)** 跟你的 PICO 相符或臨床相近
- ✅ **介入 (I)** 就是你問的那個治療（不是複方裡的其中一味）
- ✅ **結果 (O)** 直接回答你的臨床問題（不是只測 surrogate marker）
- ✅ **研究設計** 有合理的因果推論能力

如果超過一半的論文被擋在門外（例如你問的是 cardiomyopathy，但找到的都是 general heart failure；或你問臨床預後，但只找到血壓變化），這一輪就算「不足」，進入放寬策略。

### 3-Strike 放寬策略

搜尋找不到直接相關的證據時，三輪逐步放寬：

```
Strike 1 → 移除 [tiab]、日期限制等窄化條件
Strike 2 → 放寬術語（例如 "semaglutide" → "GLP-1 receptor agonist"）
Strike 3 → 停損。不改用一般網頁搜尋，不硬湊答案。
```

每一輪的 query、命中數、失敗原因都會記錄在搜尋歷程（search log）裡，最後如實呈現在停損報告中。

> **重要：** 腳本內部有一層 auto-widen（零結果時自動 strip field tags 重試），這是「零結果 recovery」，跟 agent 的 3-strike 是不同層級。詳見 SKILL.md。

## 搜尋管線

```
                    ┌─────────────────────────────────┐
                    │     pubmed_search.py             │
                    │                                  │
  Query ──────────► │  Phase 1: esearch               │
                    │  → 拿到最多 50 個 PMIDs          │
                    │  → 零結果？auto-widen strip tags  │
                    │                                  │
                    │  Phase 2: esummary + filter      │
                    │  → PublicationType 評分           │
                    │  → 年份分層 (3yr → 10yr → all)   │
                    │  → 選出 top 1-5 PMIDs            │
                    │                                  │
                    │  Phase 3: efetch                 │
                    │  → 下載完整摘要                   │
                    │  → 遞迴解析嵌套 XML 標籤          │
                    │                                  │
                    │  Output:                         │
                    │  → /tmp/pubmed_last_results.json  │
                    │  → /tmp/pubmed_search_log.json    │
                    └─────────────────────────────────┘
```

### 年份分層篩選

不是一次掃完所有年代，而是分層嘗試：

1. **Tier 1**：近 3 年 → 如果 ≥2 篇，就用這批
2. **Tier 2**：近 10 年 → 如果 ≥2 篇，就用這批
3. **Tier 3**：不限年份 → 全部排序取 top 5

優先用最新的證據，但不會因為年代限制而漏掉重要研究。

## 輸出格式

根據搜尋結果，自動選擇三種報告格式之一：

### 情境 A：找到證據

```
【🔍 EBM 臨床問題解析 (PICO)】
【📊 證據搜尋結果】
【💡 實證綜合結論】
【⚠️ 證據限制與適用性】
【📚 來源文獻參考】（每篇附 PubMed 連結）
```

### 情境 B：三輪零結果 → 停損報告

```
【⚠️ EBM 搜尋停損報告】
  → 列出三輪搜尋策略與失敗原因
【📝 研判】
【➡️ 建議下一步】
```

### 情境 C：有論文但不直接相關 → 停損報告

```
【⚠️ EBM 搜尋停損報告 — 有文獻但非直接相關】
【📋 檢索歷程與不符原因】
【📝 研判】
【➡️ 建議下一步】
```

三種格式的詳細規範見 `references/ebm-guide.md`。

## 安裝

### 🚀 最推薦：直接請 AI Agent 幫你裝

把這個 GitHub 連結貼給你正在用的 AI Agent（ChatGPT、Claude、Hermes、Cursor、Windsurf 等），然後說：

> 「幫我安裝這個 EBM Researcher skill」

連結：`https://github.com/castlen3/ebm-researcher`

Agent 會自動 clone、放到正確的目錄、設定好路徑。你不需要自己處理檔案位置。

### 相依性

**零額外依賴。** 純 Python 3 標準庫（`urllib`、`json`、`xml.etree`）。

### 作為獨立 CLI 工具

```bash
# 複製腳本
cp scripts/pubmed_search.py /usr/local/bin/
chmod +x /usr/local/bin/pubmed_search.py

# 直接用
python3 pubmed_search.py "SGLT2 inhibitor heart failure mortality"
```

### 作為 Hermes Agent Skill

```bash
# 已內建於 ~/.hermes/skills/openclaw-imports/ebm-researcher/
# Agent 透過 skill_view(name='ebm-researcher') 自動載入
```

### 作為 OpenClaw Skill

將整個目錄複製到 OpenClaw 的 skills 目錄即可。SKILL.md 的 trigger policy 會自動生效。

### 整合到其他 Agent Framework

```python
# LangChain / CrewAI / AutoGen 等 — 當 external tool 註冊
import subprocess, json

def pubmed_search(query: str) -> dict:
    result = subprocess.run(
        ["python3", "pubmed_search.py", "--json", query],
        capture_output=True, text=True,
        cwd="/path/to/ebm-researcher"
    )
    return json.loads(result.stdout)
```

### 整合到 n8n / 自動化工作流

在 n8n 的 "Execute Command" 節點中：
```
python3 /path/to/pubmed_search.py --json "{{ $json.query }}"
```
輸出的 JSON 可直接被下游節點解析。

### 包裝成 MCP Server

`pubmed_search.py --json` 的輸出格式天然適合作為 MCP tool 的 response。用 FastMCP 或 mcp-python-sdk 包一層即可註冊到任何 MCP-compatible agent。

## 使用方式

### CLI 參數

```bash
python3 pubmed_search.py [OPTIONS] "<PubMed query>"
```

| 參數 | 說明 |
|------|------|
| (無) | 人類可讀輸出（預設），含 markdown 格式摘要 |
| `--json` | JSON 輸出，供 agent 自行格式化 |
| `--log` | 在結果後追加搜尋歷程 |

### 輸出檔案

| 路徑 | 內容 |
|------|------|
| `/tmp/pubmed_last_results.json` | 最近一次搜尋的完整摘要（pmid、標題、期刊、日期、abstract、pub_types） |
| `/tmp/pubmed_search_log.json` | 搜尋歷程（每輪的 query、命中數、tier 資訊） |

Agent 可在 follow-up 問題時讀取這些快取，不用重跑搜尋。

### 使用範例

```bash
# 基本搜尋
python3 pubmed_search.py "metformin cardiovascular protection diabetes"

# JSON 模式（供 agent 使用）
python3 pubmed_search.py --json "GLP-1 receptor agonist obesity mortality"

# 帶搜尋歷程（除錯用）
python3 pubmed_search.py --json --log "aspirin primary prevention elderly"
```

## 檔案結構

```
ebm-researcher/
├── SKILL.md                    # Agent 行為規範（觸發條件、工作流程、3-strike 策略）
├── README.md                   # 本檔案
├── references/
│   └── ebm-guide.md            # 輸出格式規範（三種情境的報告模板）
└── scripts/
    └── pubmed_search.py        # PubMed 搜尋工具（獨立 CLI）
```

### 檔案職責

| 檔案 | 角色 | 給誰看 |
|------|------|--------|
| `SKILL.md` | **推理層** — 教 agent 怎麼用工具、怎麼判斷結果、什麼時候停損 | AI Agent |
| `ebm-guide.md` | **格式層** — 定義繁中報告的結構和措辭規範 | AI Agent |
| `pubmed_search.py` | **工具層** — 執行 PubMed API 呼叫、評分、篩選 | Agent 或人類 |

## 技術細節

### 評分機制

```
PublicationType（主要）         標題關鍵字（次要）
─────────────────────         ─────────────────
Meta-Analysis        → 5      "systematic review"  → 5
Systematic Review    → 5      "randomized"         → 4
RCT                  → 4      "cohort"             → 3
Clinical Trial       → 4      "clinical trial"     → 3
Observational        → 3      "case report"        → 1
Cohort Study         → 3      (default)            → 2
Case Reports         → 1

頂級期刊（NEJM/Lancet/JAMA/BMJ/Nature Medicine...）→ +1 分
```

### XML 解析

PubMed 的標題和摘要常有嵌套標籤（`<i>` 斜體、`<sup>` 上標、`<sub>` 下標）。腳本用遞迴 `extract_text()` 處理，不會截斷標題。

結構化摘要（多個 `<AbstractText Label="...">`）會保留各段標籤（BACKGROUND、METHODS、RESULTS 等）。

### 防呆設計

腳本內建防 AI 模型 hallucination：
- 自動 strip `--query`、`--max-results`、`--limit` 等不存在的參數
- 偵測到時會印警告但不中斷

## 適用平台

這個技能是 **平台無關** 的。腳本是純 Python CLI，SKILL.md 是 agent 行為知識，兩者分離。

| 平台 | 整合方式 |
|------|----------|
| **Hermes Agent** | 內建 skill，`skill_view('ebm-researcher')` 載入 |
| **OpenClaw** | 原始出處，skill 目錄直接可用 |
| **OpenCode / Claude Code / Codex** | Coding agent，把腳本當 tool call |
| **Cursor / Windsurf** | IDE 內 AI agent，有 terminal 就能跑 |
| **ChatGPT / Claude / Gemini** | 有 code interpreter → 直接執行腳本 |
| **自架 LLM (Ollama / vLLM)** | 搭配 LangChain / CrewAI / AutoGen 註冊為 tool |
| **n8n / Make / Zapier** | "Execute Command" 節點，JSON 輸出直接串下游 |
| **MCP-compatible agents** | 包裝成 MCP server tool |
| **人類直接用** | 終端機 `python3 pubmed_search.py "query"` |

## 限制

- **只查 PubMed**：不搜一般網頁、Cochrane Library、ClinicalTrials.gov
- **摘要為主**：不讀全文，可能遺漏全文裡的重要細節
- **英文文獻**：PubMed 主要收錄英文期刊
- **停損不硬湊**：找不到直接相關證據時會如實報告，不會用間接證據冒充
- **不取代臨床判斷**：這是輔助工具，最終決策仍需醫師專業判斷

---

## ⚠️ 重要聲明：本工具僅供參考

**本工具產出的所有內容不構成醫療建議，不能取代專業醫師的臨床判斷。**

- 本工具的目的是幫助**醫師、研究者、醫療專業人員**快速查找文獻，縮短從「問題」到「證據」的距離
- 搜尋結果基於 PubMed 摘要，可能遺漏全文細節、未發表數據或地區性臨床指引
- AI 綜合的結論可能有解讀偏差，**不應作為診斷、治療或處方的唯一依據**
- 任何臨床決策，請務必諮詢您的主治醫師或相關專科醫師
- 若您是患者，本工具的輸出僅供您與醫師討論時參考，**請勿自行依此調整治療**

**最終的醫療判斷，永遠應該由合格的醫師來做。**

## License

MIT
