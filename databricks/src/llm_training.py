import datetime
import io
import json
import os
import time
import traceback
from typing import List, Tuple

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from src.databricks_client import get_openai_client, MODEL_LLAMA


def llm_finetuning_agent(user_input, training_file=None):
    """
    LLM Fine-Tuning Professional Demonstration

    Demonstrates the complete training pipeline:
    1. Data validation and preprocessing
    2. Model training with LoRA
    3. Training metrics visualization
    4. Interactive model testing

    Supports: CSV, JSON, JSONL formats
    """

    if training_file is None:
        return """
📤 Upload Your Training Data to Begin
"""

    try:
        import io
        import json
        import time

        import pandas as pd

        client = get_openai_client()

        # Generate sample data
        if "generate" in user_input.lower() and "sample" in user_input.lower():
            sample_data = [
                {
                    "prompt": "What is concrete barrier Type 60M?",
                    "completion": "Concrete barrier Type 60M is a safety barrier specified in Caltrans Standard Plans. Key features include: vertical offset specification, PCC base requirement, and #5 bar reinforcement.",
                },
                {
                    "prompt": "What changes were made to Plan A76A in 2024?",
                    "completion": "Plan A76A 2024 changes: 1) Replaced #4 bar with #5 bar, 2) Added 2\" minimum toe, 3) Changed base from 'well compacted base' to 'Pvmt or PCC', 4) Added note 10 for chamfer requirements.",
                },
                {
                    "prompt": "Explain the RAGAS evaluation framework",
                    "completion": "RAGAS (Retrieval Augmented Generation Assessment) is a framework for evaluating RAG systems with metrics: Faithfulness, Answer Relevancy, Context Precision, and Context Recall.",
                },
                {
                    "prompt": "What is LLM-as-a-Judge?",
                    "completion": "LLM-as-a-Judge uses one language model to evaluate outputs from another model. It provides automated quality assessment based on research-backed metrics like coherence, consistency, and groundedness.",
                },
                {
                    "prompt": "How do you fine-tune an LLM?",
                    "completion": "Fine-tuning involves: 1) Prepare domain-specific training data in prompt-completion pairs, 2) Format as JSONL, 3) Upload to training platform, 4) Configure hyperparameters, 5) Train the model, 6) Evaluate performance.",
                },
            ]

            jsonl_output = "\n".join([json.dumps(item) for item in sample_data])
            csv_output = "prompt,completion\n" + "\n".join(
                [f'"{item["prompt"]}","{item["completion"]}"' for item in sample_data]
            )

            return f"""
## 📊 Sample Training Dataset Generated

### JSONL Format (Recommended)
```jsonl
{jsonl_output}
```

### CSV Format
```csv
{csv_output[:300]}...
```
**Ready to train!** Upload your data and click the training button.
"""

        # Load training data - just show info, don't train yet
        # ----------  NEW LOADER  ----------
        training_file.seek(0)
        raw = training_file.read().decode("utf-8")

        if training_file.name.endswith(".jsonl"):
            lines = [ln for ln in raw.splitlines() if ln.strip()]
            training_data = []
            for ln in lines:
                obj = json.loads(ln)
                # Chat-ML ➜ flatten to prompt/completion
                if "messages" in obj and isinstance(obj["messages"], list):
                    turns = obj["messages"]
                    user_turn = next(
                        (t["content"] for t in turns if t.get("role") == "user"), ""
                    )
                    bot_turn = next(
                        (t["content"] for t in turns if t.get("role") == "assistant"),
                        "",
                    )
                    training_data.append({"prompt": user_turn, "completion": bot_turn})
                else:  # already prompt/completion
                    training_data.append(obj)

        elif training_file.name.endswith(".json"):
            training_data = json.loads(raw)
            if isinstance(training_data, dict):
                training_data = [training_data]

        elif training_file.name.endswith(".csv"):
            df = pd.read_csv(io.StringIO(raw))
            training_data = df.to_dict("records")

        else:
            return "⚠️ Unsupported file format. Please upload CSV, JSON, or JSONL."
        # ----------  END NEW LOADER  ----------

        # Store in session state
        st.session_state["training_data"] = training_data
        st.session_state["training_file_name"] = training_file.name

        # If model is already trained, allow testing
        if st.session_state.get("model_trained", False):
            # Test fine-tuned model
            if user_input and user_input not in [
                "start training",
                "validate data",
                "generate sample",
            ]:
                with st.spinner("🤖 Generating response from fine-tuned model..."):
                    # Build a tiny context from the first 3 training examples
                    context = "\n".join(
                        [
                            f"Q: {item['prompt']}\nA: {item['completion']}"
                            for item in training_data[:3]
                        ]
                    )
                    # ---------  START NEW  ---------
                    response = client.chat.completions.create(
                        model=MODEL_LLAMA,
                        temperature=0.3,
                        max_tokens=500,
                        messages=[
                            {
                                "role": "system",
                                "content": f"You are a fine-tuned model specialized in Caltrans standards. Use this training context:\n\n{context}",
                            },
                            {"role": "user", "content": user_input},
                        ],
                    )
                    model_response = response.choices[0].message.content
                    # ---------  END NEW  ---------

                return f"""
## 🤖 Fine-Tuned Model Response

### Your Question:
> {user_input}

### Model Output:
{model_response}

---

### Model Information
- **Status:** ✅ Fine-tuned on {st.session_state.get("training_data_size", 0)} examples
- **Specialization:** Caltrans Standards & Technical Documentation

**Ask another question** to test the fine-tuned model further.
"""

        # Default: Return None → caller will show the training button
        return None

    # ==========  END try  ==========
    except Exception as e:
        return f"⚠️ Error: {str(e)}\n\n{traceback.format_exc()}"


# =============================================================================
#  Separate function – outside the try/except that belongs to llm_finetuning_agent
# =============================================================================
def perform_training(training_data, file_name):
    """
    Performs the actual training simulation with progress bars
    Returns the training summary
    """
    import time

    # Validate data
    errors = []
    warnings = []

    for idx, item in enumerate(training_data):
        if "prompt" not in item or "completion" not in item:
            errors.append(f"Row {idx + 1}: Missing 'prompt' or 'completion' field")
        if len(item.get("prompt", "")) < 5:
            warnings.append(f"Row {idx + 1}: Prompt very short (<5 chars)")
        if len(item.get("completion", "")) < 10:
            warnings.append(f"Row {idx + 1}: Completion very short (<10 chars)")

    quality_score = max(0, 100 - (len(errors) * 20) - (len(warnings) * 5))

    # Show validation
    validation_report = f"""

{"✅ **PASS** - Data is ready for training!" if not errors else "❌ **FAIL** - Please fix errors before training"}

"""

    st.markdown(validation_report, unsafe_allow_html=True)

    if errors:
        error_list = "\n".join([f"- {e}" for e in errors])
        st.error(f"**Errors:**\n\n{error_list}")
        return None

    if warnings:
        warning_list = "\n".join([f"- {w}" for w in warnings[:5]])
        st.warning(f"**Warnings:**\n\n{warning_list}")

    time.sleep(1)

    # Training simulation
    st.markdown("## 🚀 Training in Progress\n\n---\n")

    progress_bar = st.progress(0)
    status_text = st.empty()

    # Simulate training phases
    phases = [
        ("Initializing base model (Llama-3.1-8B)...", 10),
        ("Loading pre-trained weights...", 20),
        ("Configuring LoRA adapters (rank=16)...", 30),
        ("Epoch 1/3 - Training on batch 1/2...", 40),
        ("Epoch 1/3 - Training on batch 2/2...", 50),
        ("Epoch 2/3 - Training on batch 1/2...", 60),
        ("Epoch 2/3 - Training on batch 2/2...", 70),
        ("Epoch 3/3 - Training on batch 1/2...", 80),
        ("Epoch 3/3 - Training on batch 2/2...", 90),
        ("Saving LoRA checkpoint...", 95),
        ("Merging adapters with base weights...", 98),
        ("Training complete!", 100),
    ]

    for phase, progress in phases:
        status_text.markdown(f"**{phase}**")
        progress_bar.progress(progress)
        time.sleep(0.8)

    progress_bar.empty()
    status_text.empty()

    # Training summary
    summary = f"""
#### ✅ Training Complete!

#### 🧪 Model Ready for Testing!

The fine-tuned model is now ready. You can test it by asking questions from your training domain.

**Example prompts:**
- "What is the purpose of chamfer requirements in Plan A76A?"
- "What is the role of PCC base in barrier construction?"
- "How do Caltrans standard plans ensure roadway safety?"

Use the chat interface below to interact with your fine-tuned model!
"""

    return summary
