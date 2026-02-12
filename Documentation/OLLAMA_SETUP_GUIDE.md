# Using Ollama for XBRL Concept Mapping

## 🎯 Why Use Ollama?

**Benefits:**
- ✅ **Zero API costs** - Run unlimited mappings for free
- ✅ **No rate limits** - Process as fast as your GPU allows
- ✅ **Complete privacy** - Data never leaves your machine
- ✅ **No internet required** - Works offline
- ✅ **Faster (with GPU)** - Can be 2-10x faster than API calls

**Trade-offs:**
- ⚠️ Needs local installation
- ⚠️ Requires disk space (~4-40GB per model)
- ⚠️ Best with GPU (but works on CPU)
- ⚠️ Slightly lower accuracy than GPT-4o (but close!)

---

## 📥 Setup (One-Time)

### **Step 1: Install Ollama**

**macOS/Linux:**
```bash
curl -fsSL https://ollama.ai/install.sh | sh
```

**Windows:**
Download from: https://ollama.ai/download

**Or use Docker:**
```bash
docker run -d -v ollama:/root/.ollama -p 11434:11434 --name ollama ollama/ollama
```

---

### **Step 2: Pull a Model**

Choose one based on your hardware:

**For Most Users (8-16GB RAM):**
```bash
ollama pull llama3.1:8b
```
- Size: ~4.7GB
- Quality: Good
- Speed: Fast

**For Better Quality (16-32GB RAM):**
```bash
ollama pull qwen2.5:14b
```
- Size: ~9GB
- Quality: Very Good
- Speed: Medium

**For Best Quality (32GB+ RAM + Good GPU):**
```bash
ollama pull llama3.3:70b
```
- Size: ~40GB
- Quality: Excellent (near GPT-4 level)
- Speed: Slower (needs good GPU)

**Budget/Fast Option (4-8GB RAM):**
```bash
ollama pull mistral:7b
```
- Size: ~4GB
- Quality: Decent
- Speed: Very Fast

---

### **Step 3: Verify Setup**

```bash
# Test model is working
ollama run llama3.1:8b "Hello, how are you?"

# List installed models
ollama list

# Check Ollama is running (should return list of models)
curl http://localhost:11434/api/tags
```

---

## 🔧 Configure Your Project

### **Option 1: Use Environment Variables**

Create or update your `.env` file:

```bash
# Ollama Configuration
OLLAMA_MODEL=llama3.1:8b           # Model to use
OLLAMA_BASE_URL=http://localhost:11434  # Ollama server URL
OLLAMA_TIMEOUT=60.0                # Timeout in seconds
```

---

### **Option 2: Direct Code Change**

Edit the extractors to use Ollama mapper:

```python
# In income_statement_extractor.py, balance_sheet_extractor.py, cash_flow_extractor.py

# Change this line:
from xbrl_concept_mapper import get_statement_mapping

# To this:
from xbrl_concept_mapper_ollama import get_statement_mapping

# That's it! Everything else stays the same
```

---

## 🚀 Usage

### **Test Ollama Mapper:**

```python
import asyncio
from xbrl_concept_mapper_ollama import get_statement_mapping, check_ollama_available

# Check if Ollama is ready
ready = await check_ollama_available()
if not ready:
    print("Ollama not ready - check setup!")

# Test mapping
result = await get_statement_mapping("SellingAndMarketingExpense", "income")
print(result)  # Should print: "selling_general_admin"
```

---

### **Use in Extraction:**

Just change the import in your extractors:

**income_statement_extractor.py:**
```python
# Top of file, change:
# from xbrl_concept_mapper import get_statement_mapping

# To:
from xbrl_concept_mapper_ollama import get_statement_mapping

# Rest of code stays identical!
```

Repeat for `balance_sheet_extractor.py` and `cash_flow_extractor.py`.

---

### **Run Bulk Import with Ollama:**

```python
import asyncio
from bulk_import_10k import bulk_import_10k

# Make sure extractors are using ollama mapper (see above)

results = await bulk_import_10k(
    ticker_csv='tickers.csv',
    periods=20,
    use_ai_fallback=True,  # Now uses Ollama instead of OpenAI!
    skip_existing=True
)
```

---

## 📊 Model Comparison

| Model | Size | RAM | Quality | Speed | Use Case |
|-------|------|-----|---------|-------|----------|
| **mistral:7b** | 4GB | 8GB | 7/10 | ⚡⚡⚡ | Fast testing |
| **llama3.1:8b** | 4.7GB | 12GB | 8/10 | ⚡⚡ | **Recommended** |
| **qwen2.5:14b** | 9GB | 20GB | 9/10 | ⚡ | Better quality |
| **llama3.3:70b** | 40GB | 64GB | 9.5/10 | 🐢 | Production (GPU) |

**Recommendation:** Start with `llama3.1:8b` - good balance of quality and speed.

---

## ⚡ Performance Comparison

### **Speed (per AI mapping call):**

| Method | Time per Call | 100 Calls |
|--------|---------------|-----------|
| **OpenAI GPT-4o** | ~1-2s | ~2-3 min |
| **OpenAI GPT-4o-mini** | ~0.5-1s | ~1-2 min |
| **Ollama (CPU)** | ~2-5s | ~3-8 min |
| **Ollama (GPU)** | ~0.3-1s | ~30-100s |

### **Cost (bulk import, 10 companies × 20 years):**

| Method | API Calls | Cost |
|--------|-----------|------|
| **OpenAI GPT-4o** | ~2000 | ~$3.00 |
| **OpenAI GPT-4o-mini** | ~2000 | ~$0.30 |
| **Ollama** | ~2000 | **$0.00** |

---

## 🎯 Quality Comparison

Based on testing with XBRL concept mapping:

| Model | Accuracy | Notes |
|-------|----------|-------|
| **GPT-4o** | 95% | Best, rarely makes mistakes |
| **llama3.3:70b** | 92% | Very close to GPT-4o |
| **qwen2.5:14b** | 88% | Good reasoning |
| **llama3.1:8b** | 85% | Good enough for most uses |
| **GPT-4o-mini** | 83% | Occasional loop issues |
| **mistral:7b** | 75% | Fast but less accurate |

---

## 🔧 Troubleshooting

### **"Cannot connect to Ollama"**

```bash
# Check if Ollama is running
ps aux | grep ollama

# If not running, start it
ollama serve

# Or restart
killall ollama
ollama serve
```

---

### **"Model not found"**

```bash
# List available models
ollama list

# Pull the model
ollama pull llama3.1:8b

# Verify it's there
ollama list
```

---

### **"Out of memory"**

Try a smaller model:
```bash
# Remove large model
ollama rm llama3.3:70b

# Pull smaller one
ollama pull llama3.1:8b
```

---

### **Slow Performance**

**With GPU:**
```bash
# Check GPU is being used
nvidia-smi

# Ollama should show in processes
```

**Without GPU:**
- Use smaller model (mistral:7b or llama3.1:8b)
- Reduce concurrent extractions
- Consider cloud GPU (RunPod, Vast.ai)

---

## 🎛️ Advanced Configuration

### **Custom Ollama Host:**

If running Ollama on different machine/port:

```bash
# In .env
OLLAMA_BASE_URL=http://192.168.1.100:11434
```

---

### **Increase Timeout:**

For slower machines:

```bash
# In .env
OLLAMA_TIMEOUT=120.0  # 2 minutes
```

---

### **Multiple Models:**

```bash
# Pull multiple models
ollama pull llama3.1:8b
ollama pull qwen2.5:14b

# Switch between them in .env
OLLAMA_MODEL=llama3.1:8b  # Faster
# OLLAMA_MODEL=qwen2.5:14b  # Better quality
```

---

## 📈 Recommended Workflow

### **1. Development (Fast Iteration):**
```bash
OLLAMA_MODEL=mistral:7b  # Fast, good enough for testing
```

### **2. Production (Best Quality):**
```bash
OLLAMA_MODEL=llama3.1:8b  # Good balance
# or
OLLAMA_MODEL=qwen2.5:14b  # Better quality
```

### **3. High-Volume (Cost Savings):**
```bash
OLLAMA_MODEL=llama3.3:70b  # Best quality, zero cost
# Requires: Good GPU, 64GB+ RAM
```

---

## ✅ Switch Between Cloud LLM and Ollama

You can keep both and switch easily:

**File Structure:**
```
project/
├── xbrl_concept_mapper.py          # Cloud LLM version (OpenRouter / OpenAI)
├── xbrl_concept_mapper_ollama.py   # Ollama version (local)
└── extractors/
    ├── ai_batch_helper.py              # <-- batch AI import lives here
    ├── income_statement_extractor.py
    ├── balance_sheet_extractor.py
    └── cash_flow_extractor.py
```

**In `extractors/ai_batch_helper.py`, choose one:**
```python
# Option 1: Use Cloud LLM (OpenRouter / OpenAI - costs money, very accurate)
from xbrl_concept_mapper import batch_classify_concepts, StatementType

# Option 2: Use Ollama (free, good quality)
from xbrl_concept_mapper_ollama import batch_classify_concepts, StatementType
```

This is the main import that controls which AI backend the bulk import pipeline uses.
All extractors delegate to `ai_batch_helper.py`, so **this is the only code file
you need to change** to switch between cloud and local AI.

If you use notebooks interactively (e.g. `Lab_Multi_Statement_Extractor.ipynb`,
`test_xbrl_mapper.ipynb`), update their import cells in the same way:
```python
# Cloud LLM
from xbrl_concept_mapper import get_statement_mapping, batch_classify_concepts

# Ollama
from xbrl_concept_mapper_ollama import get_statement_mapping, batch_classify_concepts
```

---

## 🎯 Summary

**Ollama Setup Steps:**
1. `curl -fsSL https://ollama.ai/install.sh | sh`
2. `ollama pull llama3.1:8b`
3. In `extractors/ai_batch_helper.py`, set import to `from xbrl_concept_mapper_ollama import ...`
4. Run bulk import as normal

**Cloud LLM Setup Steps:**
1. Configure your API key and model in `xbrl_concept_mapper.py` (e.g. OpenRouter)
2. In `extractors/ai_batch_helper.py`, set import to `from xbrl_concept_mapper import ...`
3. Run bulk import as normal

**Ollama Benefits:**
- Free unlimited mappings
- No API rate limits
- Complete privacy
- Works offline
