# Evidence Assessment（階段 A.2）

本層不改寫 Retrieve、Student、Rc、Rv、K_int、K_ext、真假標籤或原始理由。

## 目前接通範圍

- 來源擷取：沿用原有 HTTP(S)、公開 IP、DNS pinning、TLS、4 次迭代、512 KiB、7 秒 worker 限制。新增 metadata、article/main 正文與 UTF-8 SHA-256；原 source_text 仍保留。
- YouTube：HTML 僅 metadata。`attach_public_transcript` 接收已合法取得且附公開來源的字幕；**尚未連接字幕下載服務**，不抓取／繞過限制。
- 新分析會保存 `evidence.assessment.status=disabled`。沒有任何新增真實模型呼叫。
- `assess_evidence(evidence, config, provider)` 是可注入 provider 的評估介面。尚未選定／驗證模型、憑證及費率，因此 **沒有生產環境 Google adapter**。不得把 mock 通過理解為真實 AI 已評估。
- 既有 Google SDK 使用方式已盤點；刻意不匯入 Retrieve/translator（會初始化憑證與其他流程）。未讀取 .env。

## 輸入／輸出

輸入取同一 evidence snapshot 的 video_id / analysis_id / run_id、原始 reasons、具 Rc/Rv provenance 的 claims，以及 sources。
來源優先 article_text，其次保存的 source_text；YouTube 只接受 transcript_status=obtained 的 transcript_text。不傳 K_ext、Grounding segment 或 GT。

每次模型請求：固定 system_instruction、reason_id/reason_text、claim_id/claim_text、source_id、source_field、source_text 分段、chunk_start/source_total_chars。
輸出：claim_id（或 null）、relevance、stance、target_scope、verbatim_excerpt、局部分段 excerpt_start/end、explanation。
保存記錄附 reason_id、source_id、全域位置、文字雜湊、Unicode code point 單位、模型／Prompt 版本、input、bounded raw_response、coverage、狀態及失敗原因。

只有字串與位置完全吻合才能保存引文；錯誤引文、未知 claim、非法分類、逾時等均不產生 supports/refutes。contextual/unrelated 強制 not_established；混合目標不能被當成單一支持。分段衝突標示 mixed；部分／分段無關不外推成整篇無關。
這些約束驗證結構與引文，**不能證明模型語意正確**；輸出始終標示 AI 評估。

## 配置與成本

AssessmentConfig 預設 disabled；來源上限 5、呼叫 12、每來源最多 18,000 字元、每段 3,000、目標上限 6,000 字元／32 claims、每次輸出上限參數 700 tokens、等待 15 秒。
預留額度預設每次 0.01 USD／總計 0.12 USD 是測試與 adapter 契約的限額，**不是已驗證的供應商價格或實際帳單預測**。目前實際 API 成本為零。
正式接通前必須確認模型、費率、token 計數、SDK 輸出上限、無自動重試與 transport timeout，確保每次實際成本不超過預留值；未做到前不得啟用 live provider。
逾時後停止本輪後續排程；daemon worker 只限制呼叫端等待，不能撤回已送出的遠端請求。正式 adapter 必須實作傳輸層逾時／取消。

## 重用保存結果

CLI 不重跑影片、Retrieve 或 Student：

```powershell
python -B backend/evidence_assessment.py --input backend/output/final_result.json --output-dir backend/output --enabled
```

**目前命令只保存 not_configured 狀態，不會呼叫模型。** 不加 --enabled 則保存 disabled。
寫至 output-dir/evidence_assessments/SHA256(analysis_id).json，exclusive write 不覆寫歷史；CLI 尚未提供生產 provider 參數。
Flask /student_result 與 /status 的 student_result 以唯讀方式附加該檔，但僅限影片、批次、run_id 與完整 evidence digest 一致。缺檔、壞檔、過大或過期一律保留原結果。
原始模型回覆檔完全不被 sidecar 改寫。未實作版本系統、ablation 或修正重跑。

## 限制

HTML 擷取依賴 article/main 與 metadata；無標記頁面會保留 page_text_only（可能含導覽），不保證正文完整。未做 JSON-LD、付費牆、反爬繞過、字幕下載或真實模型測試。原始 HTML 尚未保存，文字雜湊與 body 雜湊分開，不宣稱可還原原網頁。

測試例子使用明確合成文字：來源 “The bridge opened in 1990.” 可直接核對相同主張；同一來源不能證明 “The bridge video has no synthetic effects.”，mock 回覆 contextual，程式強制 not_established。不是實際新聞或正式分析結果。
