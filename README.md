# WEAVE WebApp

**Interactive, Evidence-Driven Multimodal Short-Video Misinformation Verification**

WEAVE WebApp is a research prototype built on the **Refine–Retrieve–Reason (R³)** framework. It integrates multimodal short-video understanding, external evidence retrieval, lightweight model reasoning, and human interaction in a single web application.

Rather than returning only a Real/Fake label, WEAVE lets users inspect retrieved sources, review the AI explanation, correct intermediate representations, and compare successive analysis versions.

> **Repository scope:** Web interface, runtime inference integration, evidence presentation, and interactive verification. For the complete research framework—including DSPy prompt optimization, Teacher–Student knowledge distillation, and model training—see the [WEAVE research repository](https://github.com/tyh1003/WEAVE).

<img width="2527" height="1354" alt="螢幕擷取畫面 2026-11-02 150735" src="https://github.com/user-attachments/assets/8dc2409e-6987-48f5-bac5-21d738ab3c03" />

## Overview

Short-video misinformation can involve false narration, inaccurate captions, missing context, or real footage associated with an incorrect event, time, or location. Detecting these cases requires understanding the video's claims and visual content, then checking them against relevant background information.

WEAVE separates the task into three stages:

- **Refine:** Structure the textual claims and visual content.
- **Retrieve:** Obtain internal background knowledge and externally grounded evidence.
- **Reason:** Use a fine-tuned lightweight Student Model to predict Real/Fake and generate an explanation.

The web application adds **human-first judgment, evidence inspection, interactive corrections, and versioned re-analysis**.

## Key Features

- **Video upload and analysis progress:** Submit a short video and follow the multimodal inference pipeline.
- **Human-first judgment:** Record a Real/Fake decision before reviewing the AI result.
- **Multimodal preprocessing:** Combine speech recognition, representative frames, and temporal visual descriptions.
- **External evidence:** Retrieve grounded information and inspect source links and available article summaries.
- **Human–AI comparison:** Compare the user's judgment, AI prediction, and Ground Truth when a known label is available and permitted to be displayed.
- **Explainable results:** Present the model's reasoning in the selected Traditional Chinese or English interface language, where translation is available.
- **Input Correction:** Revise an intermediate `Rc` or `Rv` representation and rerun the relevant analysis.
- **Selected News:** Choose retrieved news sources to construct a revised external-evidence input.
- **Version history:** Preserve and compare the initial analysis (V1) and subsequent versions.
- **Research tools:** Inspect available evidence assessments, ablations, baselines, version comparisons, and pipeline diagnostics.

<img width="2117" height="1249" alt="螢幕擷取畫面 2026-11-02 151318" src="https://github.com/user-attachments/assets/57a25c22-5c6e-4c90-bb9a-391b6e4dead6" />


## System Workflow

```text
                  Short Video
                       |
                       v
               Human Judgment
                       |
                       v
            Multimodal Preprocessing
             /         |         \
            v          v          v
         Frames     Speech ASR   Visual Description
             \         |         /
                       v
                Refine + Retrieve
                       |
             Rc + Rv + Kint + Kext
                       |
                       v
             Fine-tuned Student
                       |
                       v
             Prediction + Reason
                       |
                       v
          Human / AI / Ground Truth
                       |
             +---------+---------+
             |                   |
             v                   v
       Input Correction     Selected News
             |                   |
             +---------+---------+
                       |
                       v
              New Analysis Version
                       |
                       v
                Version Comparison
```


## Refine–Retrieve–Reason

### Multimodal Preprocessing

WEAVE processes complementary information from an uploaded video:

| Component | Role |
| --- | --- |
| **FFmpeg / OpenCV** | Video processing and frame extraction |
| **Whisper Large V3** | Speech transcription |
| **Representative frames** | Sampled visual evidence |
| **Qwen3-VL-4B-Instruct** | Temporal visual description |

The visual description is used to represent video content; it is not itself a final Real/Fake judgment.

### Refine

The Refine stage produces two representations:

| Field | Meaning |
| --- | --- |
| `Rc` | Refined textual claim from available text and speech |
| `Rv` | Refined video/visual content from multimodal observations |

These fields describe **what the video claims** and **what it presents**, rather than independently establishing whether those claims are true.

### Retrieve

The Retrieve stage produces:

| Field | Meaning |
| --- | --- |
| `Kint` | Internal background knowledge generated by the model |
| `Kext` | External knowledge obtained through retrieval |

The runtime retrieval component uses the **Gemini API** and **Google Search grounding**. Available grounding links and source metadata can be retained for user inspection.

External search results do not guarantee successful article fetching or extraction. Some sources may be accessible only as links.

### Reason

A fine-tuned **Gemma 3 1B Student Model** performs the final reasoning step using the structured upstream information:

```text
Rc + Rv + Kint + Kext
          |
          v
 Fine-tuned Student Model
          |
          v
 Prediction + Explanation
```

The label convention is **`0 = Real`** and **`1 = Fake / Misleading`**. The original prediction and reasoning are stored separately from any display-layer translation.

## Interactive Verification

### Human Judgment and AI Comparison

Users make an initial Real/Fake judgment before viewing the AI prediction. The result interface presents the human judgment, AI judgment, and Ground Truth where a verified label is available and disclosure is permitted.

**Ground Truth is used for evaluation and comparison, not as an input to Student Model inference.**

### News Evidence

Retrieved news sources may provide a title, publisher, date, URL, article excerpt, or AI-generated summary. When article extraction or summarization fails, the source link may still be available.

**Automatically generated summaries are not independent fact-checking results.** Source provenance and extraction metadata are maintained separately from the concise user-facing presentation.




### Input Correction

Users can inspect `Rc` and `Rv` and correct an intermediate representation when it does not accurately describe the video. A correction creates a new analysis version, preserving the original result.

<img width="1198" height="978" alt="螢幕擷取畫面 2026-11-02 223909" src="https://github.com/user-attachments/assets/88d291da-d475-4319-8c1b-4e2de320fea8" />

### Selected News

Users can select available retrieved sources to construct a revised external-evidence input (`Kext`) for a new version. This makes it possible to examine how different evidence selections affect the subsequent Student prediction and explanation.


<img width="1216" height="1237" alt="螢幕擷取畫面 2026-11-02 225617" src="https://github.com/user-attachments/assets/46f7d9f9-d4e4-402c-abe5-a50deb08bad1" />

### Version Comparison

The original run is **V1**. Later user-initiated analyses are saved as separate versions rather than overwriting V1. Version comparison allows users to inspect changes in inputs, evidence, predictions, and explanations.

A changed prediction does **not** by itself prove that a corrected input or selected source is more reliable.


<table align="center">
  <tr>
    <td colspan="2" align="center">
      <img width="100%" alt="第三張圖片"
        src="https://github.com/user-attachments/assets/bedaf185-097c-4edd-bbb3-00a9551a9c8a" />
    </td>
  </tr>
  <tr>
    <td width="50%" align="center">
      <img width="100%" alt="第二張圖片"
        src="https://github.com/user-attachments/assets/cb16cbe0-6bbb-4bd5-844d-836c91d1236c" />
    </td>
    <td width="50%" align="center">
      <img width="100%" alt="第一張圖片"
        src="https://github.com/user-attachments/assets/489502c0-0c1b-4922-9c86-36902cd05d6c" />
    </td>
  </tr>
</table>


## Advanced Research

WEAVE includes research-oriented tools for inspecting the relationship between evidence and model outputs. Depending on the available saved data, these include:

| Tool | Purpose |
| --- | --- |
| Evidence Assessment | Inspect claim–source relationships |
| Evidence-grounded Explanation | Present additional source-associated analysis |
| Evidence Ablation | Compare outcomes with modified evidence availability |
| Source-grounded Baseline | Provide an evidence-oriented reference analysis |
| Version Comparison | Compare saved versions and their outputs |
| Pipeline Diagnostics / Research Data | Inspect execution records and provenance |

Some tools perform additional analysis after the Student prediction. Their outputs should **not** be interpreted as the Student Model's original internal reasoning.

## Research vs. Runtime Pipeline

The broader research project includes development-time stages such as **DSPy prompt optimization, Teacher Model reasoning, distillation dataset construction, and Student Model fine-tuning**.

```text
Research / Training:
Preprocess -> Retrieve -> DSPy Optimization -> Teacher Reason
           -> Distillation Dataset -> Student Fine-tuning

Web Runtime:
Preprocess -> Refine + Retrieve -> Trained Student -> Result
```

Training and prompt optimization are **not executed for every uploaded video**. See the [WEAVE research repository](https://github.com/tyh1003/WEAVE) for the broader implementation.

## Technology Stack

| Layer | Technologies |
| --- | --- |
| Frontend | Vue 3, Vite, JavaScript, Tailwind CSS |
| Backend | Python, Flask |
| Video / audio | FFmpeg, OpenCV, Whisper Large V3 |
| Visual understanding | Qwen3-VL-4B-Instruct |
| Retrieval | Gemini API, Google Search grounding |
| Student reasoning | Gemma 3 1B, PyTorch, Transformers, PEFT / LoRA |
| Research / training | DSPy, Teacher–Student distillation, QLoRA |

## Getting Started

### Requirements

- Node.js and npm
- Python and the dependencies specified by the repository
- FFmpeg
- A compatible CUDA/GPU environment for local multimodal models
- Required model weights and fine-tuned adapter files
- Gemini API credentials for external retrieval

Running the frontend alone is substantially less demanding than running the complete AI pipeline.

### Clone the Repository

```bash
git clone https://github.com/tyh1003/WEAVE-WebApp.git
cd WEAVE-WebApp
```

### Frontend

```bash
npm install
npm run dev
```

Open the local URL shown by Vite.

### Backend

Create a Python environment:

```bash
python -m venv .venv
```

Activate it on Windows (PowerShell):

```powershell
.venv\Scripts\Activate.ps1
```

Or on macOS/Linux:

```bash
source .venv/bin/activate
```

Install dependencies from the project root:

```bash
pip install -r requirements.txt
```

Then start the backend:

```bash
cd backend
python app.py
```

The frontend and backend run as separate processes in development. Host, port, and proxy settings depend on the local configuration.

> **Note:** Model downloads, adapter paths, GPU-specific packages, and API configuration may require additional setup. These are basic development entry points, not a guarantee that full inference will run on every machine.

### Environment Configuration

Configure required backend credentials locally, for example:

```dotenv
GEMINI_API_KEY=your_api_key_here
```

Never commit actual API keys, `.env` files, or private credentials. When accessing the frontend from another device, ensure that its API base URL points to the reachable backend rather than the browser device's `localhost`.

## Repository Structure

```text
WEAVE-WebApp/
├── backend/          # Flask APIs, inference integration, evidence logic
├── src/              # Vue application and components
├── public/           # Static assets
├── experiments/      # Research utilities, where included
├── docs/
│   └── images/       # Reserved for new screenshots and diagrams
├── package.json
├── requirements.txt
├── vite.config.js
└── README.md
```

The exact contents of some directories depend on the checked-out revision.

## Evaluation and Demonstration

WEAVE is intended as an **interactive research prototype**. A demonstration can show the initial human judgment, AI prediction, retrieved evidence, an input correction or news selection, and the resulting version comparison.

Representative qualitative case studies may include typical misinformation, authentic content, and misleading narratives built around real events. Where available, single-run profiling can document stage latency, API activity, and token usage.

**No accuracy, latency, or cost benchmark is claimed here without a documented measurement.**

<img width="2117" height="1249" alt="螢幕擷取畫面 2026-11-02 151318" src="https://github.com/user-attachments/assets/feb80ea8-b79c-4de8-ad60-3ac78087005a" />
<img width="2119" height="1242" alt="螢幕擷取畫面 2026-11-02 221058" src="https://github.com/user-attachments/assets/b28dc0f2-6bad-4b75-9750-aac8a7b65103" />
<img width="2122" height="1244" alt="螢幕擷取畫面 2026-11-02 222448" src="https://github.com/user-attachments/assets/f6388e25-bfa3-4146-b0ec-9628c8e75fe0" />


## Limitations

- **External-source availability:** Search results and source accessibility vary over time.
- **Article extraction:** Some pages may time out, reject extraction, or exceed size limits.
- **Evidence quality:** Retrieved information and AI-generated summaries are not independently verified facts.
- **Model reliability:** AI predictions and explanations may be inaccurate.
- **Ground Truth coverage:** Verified labels are available only for supported items and subject to disclosure rules.
- **Resource requirements:** Local multimodal models require compatible hardware; external APIs may incur costs.
- **Interpretation:** Interactive edits and ablations illustrate sensitivity to evidence, not guaranteed improvement or causal faithfulness.

WEAVE is a **research prototype**, not a production fact-checking authority.

## Related Research Repository

**[WEAVE — Refine–Retrieve–Reason Research Framework](https://github.com/tyh1003/WEAVE)**

The research repository contains the broader model development and experimental pipeline, while this repository focuses on interactive web inference and evidence inspection.

---

**WEAVE WebApp** · Interactive Multimodal Short-Video Misinformation Verification
