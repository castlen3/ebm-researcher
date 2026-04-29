# EBM Output Formatting & Guidelines

This document defines how the `ebm-researcher` skill should format its final answer.

## Strict Rules
1. **No code blocks in user-facing replies:** avoid backticks and terminal-style output.
2. **No raw tool errors:** never show commands, JSON blobs, stack traces, or stderr.
3. **Traditional Chinese:** write the report in fluent Traditional Chinese (Taiwan).
4. **Separate evidence from interpretation:** clearly distinguish what the papers show versus your synthesis.
5. **State limitations explicitly:** if evidence is weak, indirect, inconsistent, small-sample, or low-quality, say so clearly.

---

## Scenario A: Evidence Found

When 1-5 clinically relevant papers are retrieved, use this structure:

**【🔍 EBM 臨床問題解析 (PICO)】**
- **P (對象)**: [簡述族群]
- **I (介入)**: [簡述治療/暴露]
- **C (比較)**: [簡述比較組；若無則寫「無明確比較」]
- **O (結果)**: [主要臨床結果]

**【📊 證據搜尋結果】**
- 共納入 [X] 篇與問題最相關的文獻
- 研究類型包含：[例如 meta-analysis / RCT / cohort]
- 若有重要限制，先在這裡用一句話點出

**【💡 實證綜合結論】**
[用 1-2 段繁中整理臨床上可用的結論。]

撰寫原則：
- 先講整體方向，再補充例外與限制
- 若文獻結果彼此衝突，明確指出差異與可能原因
- 若只能支持「可能有效」或「證據不足」，不要寫成肯定句
- 若外部效度有限，說明適用族群限制

**【⚠️ 證據限制與適用性】**
- [樣本數、追蹤時間、偏倚風險、異質性、間接性、族群不符等]

**【📚 來源文獻參考】**
1. [期刊縮寫, 年份] 標題
   🔗 https://pubmed.ncbi.nlm.nih.gov/PMID/
   - 一句話總結該篇貢獻
2. [期刊縮寫, 年份] 標題
   🔗 https://pubmed.ncbi.nlm.nih.gov/PMID/
   - 一句話總結該篇貢獻

每篇文獻都必須附上可點擊的 PubMed 連結，且連結獨立一行。

---

## Scenario B: Stop-Loss After 3 Search Attempts

If 3 search-widening rounds still fail to find sufficiently relevant PubMed evidence, use this structure:

**【⚠️ EBM 搜尋停損報告】**

針對此臨床問題（[簡述問題]），我已在 PubMed 進行 3 輪逐步放寬的搜尋：
1. 初始 PICO 導向搜尋：[第一次策略摘要] → [失敗原因]
2. 放寬限制後搜尋：[第二次策略摘要] → [失敗原因]
3. 擴大同義詞/上位概念後搜尋：[第三次策略摘要] → [失敗原因]

**【📝 研判】**
目前 PubMed 上可能缺乏足以直接回答此問題的高相關臨床證據，或現有證據以低階、間接、非人體研究為主。

**【➡️ 建議下一步】**
- 可改查更上位的藥物類別或介入策略
- 可放寬到動物實驗或機轉研究，但需明確標註證據層級較低
- 可重新定義族群、介入或 outcome 後再做一次新的 EBM 搜尋

重點：停損後不要改用一般網頁搜尋來補臨床證據。

---

## Scenario C: Papers Retrieved BUT Fail Directness Gate

Sometimes you retrieve papers, but they don't actually answer the clinical question. Use this structure when ALL of the following are true:
- At least some papers were retrieved (not zero)
- But they fail the Directness Gate (off-target population, off-target outcome, off-target intervention, or too low-level)
- This happened across 2-3 search rounds

**【⚠️ EBM 搜尋停損報告 — 有文獻但非直接相關】**

針對此臨床問題（[簡述問題]），雖在 PubMed 檢索到若干文獻，但經過 Directness Gate 審視後，這些文獻**無法直接回答您的臨床問題**。

**【📋 檢索歷程與不符原因】**
- 初始搜尋：檢索到 [X] 篇 → 問題：[例如族群不符 / 僅動物研究 / 僅測 surrogate endpoint / 僅複方無法單獨判斷療效]
- 第一次放寬：檢索到 [Y] 篇 → 問題：同上
- 第二次放寬：檢索到 [Z] 篇 → 問題：同上

**【📝 研判】**
現有 PubMed 文獻的標的與您的臨床問題**不夠直接對應**，可能原因包括：
- 族群差異：例如您問的是 cardiomyopathy，但找到的多是 general heart failure 或健康志願者
- 介入差異：例如您問的是單一成分，但找到的是複方研究
- 結果差異：例如您問的是臨床預後，但找到的僅有 surrogate markers
- 證據層級：找到的主要是動物/體外研究，無法直接外推到人體臨床

**【➡️ 建議下一步】**
- 可嘗試重新界定 PICO 元素（例如擴大族群定義、放寬介入範圍）
- 若願意接受**較間接的證據層級**（動物實驗、機轉研究、surrogate outcomes），可明確告知我放寬範圍
- 可考慮改查系統性回顧或共識指引（但這些可能不見得存在）

重點：此情況下仍**不應改用一般網頁搜尋**來補臨床證據，應如實回報間接性限制。

---

## Curl Fallback: Relevance Scoring Rules

When using curl + NCBI E-utilities as fallback (instead of `pubmed_search.py`), apply these rules to select the top 1-5 PMIDs for efetch.

### Step 1: Check PublicationType (preferred)

The esummary response includes `pubtype[]` for each article. Use this first:

| PublicationType | Score |
|---|---|
| Meta-Analysis, Systematic Review | 5 |
| Randomized Controlled Trial, Clinical Trial | 4 |
| Observational Study, Cohort Study, Multicenter Study | 3 |
| Review, Comparative Study | 3 |
| Case Reports, Editorial, Letter, Comment | 1 |
| (no match / unknown) | 2 |

### Step 2: Fallback to title keywords

If pubtype is missing or doesn't help distinguish:

Score each article by keywords in the title:
- **5 pts**: `systematic review`, `meta-analysis`, `meta analysis`, `cochrane`
- **4 pts**: `randomized`, `randomised`, `rct`, `double-blind`, `placebo-controlled`
- **3 pts**: `cohort`, `case-control`, `prospective`, `retrospective`, `clinical trial`, `clinical study`, `observational`
- **2 pts**: `patient`, `therapy`, `treatment`, `diagnosis`, `outcome`, `efficacy`, `safety`
- **1 pt**: `case report`, `case series`, `editorial`, `letter`, `commentary`
- Default: 2 pts (moderate relevance) if no keywords match

### Top Journal Bonus (+1 pt)

NEJM, The Lancet, JAMA, Nature Medicine, BMJ, Nature, Science, Cell, Annals of Internal Medicine, Circulation, The BMJ, JAMA Internal Medicine, Lancet Respiratory Medicine, European Heart Journal, JAMA Cardiology, Gastroenterology, Hepatology.

### Tiered Year Filtering

1. **Tier 1**: Articles from last 3 years → if ≥2 found, sort by score desc, take top 5
2. **Tier 2**: Articles from last 10 years → if ≥2 found, sort by score desc, take top 5
3. **Tier 3**: All articles, any year → sort by score desc, take top 5

Note: `pubmed_search.py` already applies identical scoring and tiering internally — these rules only apply when using the curl fallback path.
