# Annotation Demo

This is a minimal demo system for LLM-based annotation with reflective memory.

---

## 🛠️ Setup Environment

We recommend using a **virtual environment** to avoid dependency conflicts.

### Option 1: Using `venv` (recommended)

```bash
cd annotation_demo

# create virtual environment (Python 3.9+)
python3 -m venv .venv

# activate (macOS / Linux)
source .venv/bin/activate

# activate (Windows PowerShell)
# .venv\Scripts\Activate.ps1

# upgrade pip
pip install --upgrade pip

# install project (editable mode)
pip install -e .
```

---

### Option 2: Using `conda`

```bash
conda create -n annotation_demo python=3.10
conda activate annotation_demo

pip install -e .
```

---

## 🔑 Set API Key

```bash
export OPENAI_API_KEY=your_key_here
```

For Windows:

```powershell
setx OPENAI_API_KEY "your_key_here"
```

---

## ✅ Verify Installation

```bash
python -c "import annotation_demo; print('Setup successful 🚀')"
```

---

## 📁 Project Structure

```
annotation_demo/
  src/
    annotation_demo/
      ...
```

---

## 🚀 Run Demo (TBD)

Coming soon.

---

## 🧠 Notes

* This project uses a clean virtual environment (`.venv/`)
* Do not install dependencies into base/conda root environments
* If you encounter dependency issues, recreate the environment

---
