import os
import json
import yaml
import torch
from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig
from peft import PeftModel

class StudentBot:
    def __init__(self, config_path="config/student_bot_config.yaml", epoch_dir=None):
        """
        初始化小型機器人，載入基礎模型與特定 Epoch 的 LoRA 權重
        :param config_path: 機器人配置檔案路徑
        :param epoch_dir: 指定要載入的權重路徑（例如: "./model/gemma2_2b_rag_finetuned/epoch_2"）
        """
        # 1. 讀取設定檔
        with open(config_path, 'r', encoding='utf-8') as f:
            self.config = yaml.safe_load(f)
            
        self.system_prompt = self.config.get("system_prompt", "")
        self.max_length = self.config.get("max_length", 768)
        self.base_model_name = self.config.get("model_name", "google/gemma-2-2b-it")
        
        # 優先使用外部傳入的 epoch_dir，否則沿用設定檔內的預設值
        self.lora_dir = epoch_dir if epoch_dir else self.config.get("epoch_dir")
        
        if self.lora_dir and not os.path.isabs(self.lora_dir):
            self.lora_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(config_path))), self.lora_dir)
        if not self.lora_dir:
            raise ValueError("找不到有效的 LoRA 權重路徑！請檢查設定檔或手動傳入 epoch_dir。")
            
        print(f"正在啟動小型機器人...")
        print(f"基礎模型: {self.base_model_name}")
        print(f"增量權重路徑: {self.lora_dir}")

        # 2. 設定 4-bit 量化配置（與微調時保持一致）
        bnb_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.float16,
            bnb_4bit_use_double_quant=True
        )

        # 3. 載入分詞器 (Tokenizer)
        # 優先從 LoRA 資料夾載入分詞器，若無則從基礎模型載入
        try:
            self.tokenizer = AutoTokenizer.from_pretrained(self.lora_dir, padding_side="left")
            print("成功從 LoRA 目錄載入 Tokenizer")
        except Exception:
            self.tokenizer = AutoTokenizer.from_pretrained(self.base_model_name, padding_side="left")
            print("從基礎模型載入 Tokenizer")
            
        if self.tokenizer.pad_token is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token

        # 4. 載入 4-bit 基礎模型，並疊加指定的 LoRA 增量權重
        print("正在將基礎模型載入至 GPU (4-bit)...")
        base_model = AutoModelForCausalLM.from_pretrained(
            self.base_model_name,
            quantization_config=bnb_config,
            device_map="auto",
            torch_dtype=torch.float16,
            attn_implementation="sdpa"  # 確保與 T4 顯卡環境相容
        )
        
        print("正在疊加指定的 LoRA 權重...")
        self.model = PeftModel.from_pretrained(base_model, self.lora_dir)
        self.model.eval()  # 切換至推論模式
        print("小型機器人初始化成功！隨時可以進行真偽預測。")

    def _format_knowledge_list(self, items):
        """格式化知識列表，與訓練 Dataset 保持完全一致"""
        if isinstance(items, list):
            items = [str(x).strip() for x in items if str(x).strip()]
        elif not items:
            return "無"
        else:
            items = [str(items).strip()]
        
        if not items:
            return "無"
        return "\n".join([f"- {x}" for x in items])

    def predict(self, Rc, Rv, K_int=None, K_ext=None):

        formatted_k_int = self._format_knowledge_list(K_int)
        formatted_k_ext = self._format_knowledge_list(K_ext)

        # ==================== 從 YAML 建立 User Prompt ====================

        user_prompt_template = self.config.get(
            "USER_PROMPT_TEMPLATE",
            ""
        )

        if not user_prompt_template:
            raise ValueError(
                "student_bot_config.yaml 缺少 USER_PROMPT_TEMPLATE"
            )

        user_prompt = user_prompt_template.format(
            Rc=Rc,
            Rv=Rv,
            K_int=formatted_k_int,
            K_ext=formatted_k_ext
        )

        # ==================== Chat Template ====================

        prompt_text = (
            f"{self.system_prompt}\n\n"
            f"{user_prompt}"
        )

        chat_messages = [
            {
                "role": "user",
                "content": prompt_text
            }
        ]

        prompt_formatted = self.tokenizer.apply_chat_template(
            chat_messages,
            tokenize=False,
            add_generation_prompt=True
        )

        # ==================== Tokenize ====================

        inputs = self.tokenizer(
            prompt_formatted,
            return_tensors="pt",
            truncation=True,
            max_length=self.max_length
        ).to(self.model.device)

        self.last_trace = {
            "model": self.base_model_name, "config": self.config,
            "messages": chat_messages, "formatted_prompt": prompt_formatted,
            "effective_input_ids": inputs["input_ids"].detach().cpu().tolist(),
            "effective_attention_mask": inputs["attention_mask"].detach().cpu().tolist(),
            "truncation": True, "max_length": self.max_length,
            "generation": {"max_new_tokens": 256, "do_sample": False, "eos_token_id": self.tokenizer.eos_token_id, "pad_token_id": self.tokenizer.pad_token_id},
            "raw_response": None,
            "generated_ids": None,
            "fields": {"Rc": Rc, "Rv": Rv, "K_int": K_int, "K_ext": K_ext},
        }
        if os.getenv("WEAVE_WORK_DIR"):
            trace_path = os.path.join(os.environ["WEAVE_WORK_DIR"], "output", "student_trace.json")
            with open(trace_path, "w", encoding="utf-8") as trace_file:
                json.dump(self.last_trace, trace_file, ensure_ascii=False, indent=2)

        # ==================== Generate ====================

        with torch.no_grad():
            outputs = self.model.generate(
                **inputs,
                max_new_tokens=256,
                do_sample=False,
                eos_token_id=self.tokenizer.eos_token_id,
                pad_token_id=self.tokenizer.pad_token_id
            )

        # ==================== Decode ====================

        generated_ids = outputs[0][
            inputs["input_ids"].shape[-1]:
        ]

        response_text = self.tokenizer.decode(
            generated_ids,
            skip_special_tokens=True
        ).strip()

        print("\n" + "=" * 60)
        print("RAW STUDENT OUTPUT")
        print("=" * 60)
        print(response_text)
        print("=" * 60)

        self.last_trace.update(raw_response=response_text, generated_ids=generated_ids.detach().cpu().tolist())
        pred_label = -1
        reason = response_text

        # ==================== JSON Parse ====================

        try:
            start_idx = response_text.find("{")
            end_idx = response_text.rfind("}")

            if (
                start_idx != -1
                and end_idx != -1
                and end_idx > start_idx
            ):
                json_str = response_text[
                    start_idx:end_idx + 1
                ]
            else:
                json_str = response_text

            res_obj = json.loads(json_str)

            pred_label = int(
                res_obj.get("pred_label", -1)
            )

            reason = str(
                res_obj.get(
                    "reason",
                    "無法解析原因"
                )
            ).strip()

        # ==================== Fallback Parse ====================

        except Exception as e:
            import re

            print(
                f"[StudentBot] JSON parse failed: {e}"
            )

            pred_match = re.search(
                r'"pred_label"\s*:\s*(\d+)',
                response_text
            )

            reason_match = re.search(
                r'"reason"\s*:\s*"([^"]*)"',
                response_text,
                re.DOTALL
            )

            if pred_match:
                pred_label = int(
                    pred_match.group(1)
                )

            if reason_match:
                reason = (
                    reason_match
                    .group(1)
                    .strip()
                )

        # ==================== Validate ====================

        if pred_label not in (0, 1):
            print(
                "[StudentBot Warning] "
                f"非法 pred_label: {pred_label}"
            )

        return pred_label, reason

if __name__ == "__main__":
    # 本地或測試時的模擬調用測試
    # 確保路徑指向你的 epoch_1 資料夾
    test_epoch_path = "./model/gemma2_2b_rag_finetuned/epoch_2"
    
    if os.path.exists(test_epoch_path):
        bot = StudentBot(config_path="config/student_bot_config.yaml", epoch_dir=test_epoch_path)
        
        # 定義多筆測試數據列表 (包含多種事實查核情境)
        test_dataset = [
            {
                "case_name": "案例 1：完全虛假的醫療謠言 (假訊息)",
                "Rc": "網傳喝綠茶可以消滅體內所有的癌細胞。",
                "Rv": "畫面中一名老中醫正在泡茶，字幕打上綠茶是防癌之王。",
                "K_int": ["綠茶含有茶多酚，具有抗氧化作用。"],
                "K_ext": ["醫學證實，茶多酚無法直接取代癌症藥物，且沒有臨床證據支持喝茶能消滅體內所有癌細胞。"]
            },
            {
                "case_name": "案例 2：日常科學與氣象常識 (真實訊息)",
                "Rc": "中央氣象署發布強烈颱風警報，提醒沿海地區嚴防海水倒灌與強風豪雨。",
                "Rv": "新聞氣象主播站在衛星雲圖前，畫面顯示颱風眼清晰，暴風圈已逼近台灣東部海域。",
                "K_int": ["氣象署於今日下午發布了強烈颱風海上陸上颱風警報。"],
                "K_ext": ["衛星雲圖與氣象觀測資料顯示，該颱風確實達到強烈颱風等級，且路徑直撲台灣。"]
            },
            {
                "case_name": "案例 3：誇大不實的財經投資 (部分誤導/誇大)",
                "Rc": "只要加入這個 LINE 投資群組，保證每個月穩賺 300% 獲利，完全零風險！",
                "Rv": "影片中展示滿桌的現鈔、名車鑰匙，並有一名自稱投顧老師的人在黑板上畫暴漲的股票走勢圖。",
                "K_int": ["合法的證券投資信託業務必須獲得金管會核准，且任何投資均有風險。"],
                "K_ext": ["刑事警察局 165 反詐騙中心多次公告，此類『高獲利、零風險』的群組均為典型的虛擬貨幣或電信詐騙手法。"]
            },
            {
                "case_name": "案例 4：舊聞新炒、圖文不符 (移花接木)",
                "Rc": "突發！某市中心今日下午發生嚴重連環車禍，現場火光沖天，交通完全癱瘓！",
                "Rv": "影片顯示多輛消防車在現場灌救，背景建築物有明顯的英文招牌，街景看起來不像台灣。",
                "K_int": ["本地消防局今日下午並未接獲任何市中心重大連環車禍或火災報案。"],
                "K_ext": ["透過圖片反向搜索，該影片實為三年前美國加州一起化學槽車爆炸的舊新聞畫面，並非今日發生的事件。"]
            }
        ]
        
        print("\n" + "="*50)
        print("開始執行多筆模擬數據測試...")
        print("="*50)
        
        # 迴圈跑完所有測試數據並排版輸出
        for idx, data in enumerate(test_dataset, 1):
            print(f"\n [{idx}] 測試情境: {data['case_name']}")
            print(f" [輸入文字] Rc: {data['Rc']}")
            print(f" [輸入視覺] Rv: {data['Rv']}")
            print(f" [內部知識] K_int: {data['K_int']}")
            print(f" [外部知識] K_ext: {data['K_ext']}")
            print("模型推理中...")
            
            # 呼叫預測函式
            label, res, kn = bot.predict(
                Rc=data["Rc"],
                Rv=data["Rv"],
                K_int=data["K_int"],
                K_ext=data["K_ext"]
            )
            
            # 格式化輸出結果
            print(f"\n---  預測結果 (案例 {idx}) ---")
            print(f"   預測標籤 (pred_label) : {label}")
            print(f"   判斷理由 (reason)     : {res}")
            print(f"   提取知識 (knowledge)  : {kn}")
            print("="*50)
            
        print("\n 所有模擬測試數據執行完畢！")
        
    else:
        print(f"請確認測試路徑是否存在: {test_epoch_path}")

    print("===== SYSTEM PROMPT =====")
    print(bot.system_prompt)
    print("=========================")
