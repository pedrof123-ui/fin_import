# WSL + Ollama Setup Guide

## 🎯 Problem

You're running:
- **Python project in WSL** (Ubuntu/Linux)
- **Ollama on Windows**
- Windows host IP changes dynamically

## ✅ Solution

The `xbrl_concept_mapper_ollama.py` now **automatically detects** the Windows host IP from WSL!

---

## 🚀 Quick Setup

### **Step 1: Ensure Ollama is Running on Windows**

In Windows PowerShell or Command Prompt:

```powershell
# Start Ollama
ollama serve
```

**Important:** Make sure Ollama is listening on all interfaces, not just localhost.

In Windows, set environment variable:
```powershell
# PowerShell
$env:OLLAMA_HOST="0.0.0.0"
ollama serve

# Or permanently:
[System.Environment]::SetEnvironmentVariable('OLLAMA_HOST', '0.0.0.0', 'User')
```

---

### **Step 2: Test Connection from WSL**

Run the test script:

```bash
cd ~/projects/fin_import2
python test_wsl_ollama.py
```

**Expected output:**
```
✅ Running in WSL
✅ Windows host IP: 172.17.112.1
✅ Port 11434 is open
✅ Ollama API responding
✅ Ollama is accessible
```

---

### **Step 3: Configure (Optional)**

The mapper **auto-detects** the Windows IP, but you can override:

**Option A: Let it auto-detect (Recommended)**
```bash
# No configuration needed!
# Mapper automatically finds Windows host
```

**Option B: Set explicitly in .env**
```bash
# In your .env file
OLLAMA_HOST=172.17.112.1
OLLAMA_MODEL=deepseek-r1:8b
```

**Option C: Use environment variable**
```bash
# Get current IP
WIN_HOST=$(ip route | awk '/default/ {print $3; exit}')

# Set for current session
export OLLAMA_HOST=$WIN_HOST

# Or add to ~/.bashrc for persistence
echo "export OLLAMA_HOST=\$(ip route | awk '/default/ {print \$3; exit}')" >> ~/.bashrc
```

---

## 🔧 Windows Firewall Setup

If connection fails, configure Windows Firewall:

### **Option 1: Quick (Disable for Private Networks)**

1. Open **Windows Security** → **Firewall & network protection**
2. Click **Private network**
3. Turn off **Windows Defender Firewall** (for private network only)

### **Option 2: Proper (Create Inbound Rule)**

1. Open **Windows Defender Firewall with Advanced Security**
2. Click **Inbound Rules** → **New Rule**
3. **Port** → **Next**
4. **TCP** → **Specific local ports**: `11434` → **Next**
5. **Allow the connection** → **Next**
6. Check all (Domain, Private, Public) → **Next**
7. Name: `Ollama WSL Access` → **Finish**

---

## 🧪 Testing

### **Test 1: Port Connectivity**

```bash
# Get Windows IP
WIN_HOST=$(ip route | awk '/default/ {print $3; exit}')

# Test port
nc -zv $WIN_HOST 11434
```

**Expected:** `Connection to 172.17.112.1 11434 port [tcp/*] succeeded!`

---

### **Test 2: API Connectivity**

```bash
# Test Ollama API
WIN_HOST=$(ip route | awk '/default/ {print $3; exit}')
curl http://$WIN_HOST:11434/api/tags
```

**Expected:** JSON response with model list

---

### **Test 3: Python Test**

```python
import asyncio
from xbrl_concept_mapper_ollama import check_ollama_available

# Test connection
ready = await check_ollama_available()

if ready:
    print("✅ Ollama ready!")
else:
    print("❌ Ollama not accessible")
```

---

## 🎯 How Auto-Detection Works

The mapper automatically:

1. **Detects if running in WSL** (checks `/proc/version`)
2. **Gets Windows host IP** using `ip route show default`
3. **Constructs URL** as `http://{windows_ip}:11434`
4. **Falls back to localhost** if not in WSL

**Code:**
```python
def get_windows_host_ip() -> str:
    """Auto-detect Windows host from WSL"""
    try:
        with open('/proc/version', 'r') as f:
            if 'microsoft' in f.read().lower():
                # In WSL - get Windows IP
                result = subprocess.run(['ip', 'route', 'show', 'default'], ...)
                # Parse: "default via 172.17.112.1 dev eth0"
                return extracted_ip
    except:
        pass
    return 'localhost'
```

---

## 📋 Environment Priority

The mapper checks in this order:

1. **`OLLAMA_BASE_URL`** (if set) - highest priority
2. **`OLLAMA_HOST`** (if set) - medium priority  
3. **Auto-detection** - default (WSL → Windows IP, otherwise localhost)

---

## 🔍 Troubleshooting

### **Issue: "Cannot connect to Ollama"**

**Check 1: Ollama running?**
```powershell
# On Windows
Get-Process ollama
```

**Check 2: Listening on all interfaces?**
```powershell
# On Windows
$env:OLLAMA_HOST="0.0.0.0"
ollama serve
```

**Check 3: Firewall allowing connections?**
```bash
# From WSL
nc -zv $(ip route | awk '/default/ {print $3}') 11434
```

**Check 4: Correct IP detected?**
```bash
# From WSL
ip route | awk '/default/ {print $3; exit}'
```

---

### **Issue: "Model not found"**

```bash
# List available models
curl http://$(ip route | awk '/default/ {print $3}'):11434/api/tags

# Pull model (run on Windows)
ollama pull deepseek-r1:8b
```

---

### **Issue: IP keeps changing**

The auto-detection handles this! Each time the mapper runs, it checks the current IP.

**But if you want persistence:**
```bash
# Add to ~/.bashrc
echo 'export OLLAMA_HOST=$(ip route | awk "/default/ {print \$3; exit}")' >> ~/.bashrc
source ~/.bashrc
```

---

## ✅ Verification

After setup, verify everything works:

```python
import asyncio
from xbrl_concept_mapper_ollama import get_statement_mapping, check_ollama_available

async def test():
    # Check connection
    print("Checking Ollama...")
    ready = await check_ollama_available()
    
    if ready:
        # Test mapping
        result = await get_statement_mapping("Revenue", "income")
        print(f"Test mapping: Revenue → {result}")
        return True
    return False

# Run test
await test()
```

**Expected output:**
```
Detected WSL Windows host IP: 172.17.112.1
Ollama configuration: http://172.17.112.1:11434 (model: deepseek-r1:8b)

Checking Ollama availability...
  URL: http://172.17.112.1:11434
  Model: deepseek-r1:8b
✅ Ollama ready with model: deepseek-r1:8b

Mapper called: Revenue (income) → revenue
Test mapping: Revenue → revenue
```

---

## 🎯 Summary

**What you need to do:**
1. Run `ollama serve` on Windows with `OLLAMA_HOST=0.0.0.0`
2. Configure Windows Firewall to allow port 11434
3. Run `python test_wsl_ollama.py` to verify
4. Use the mapper - it auto-detects Windows IP!

**What the mapper does automatically:**
- Detects WSL environment
- Gets current Windows host IP
- Constructs correct URL
- Works even when IP changes

No manual configuration needed!

---

## Switching to a Cloud LLM Instead of Ollama

If you prefer to use a cloud LLM (e.g. OpenRouter) instead of running Ollama locally,
you only need to change one import in the codebase:

**In `extractors/ai_batch_helper.py`, change:**
```python
# From (Ollama):
from xbrl_concept_mapper_ollama import batch_classify_concepts, StatementType

# To (Cloud LLM):
from xbrl_concept_mapper import batch_classify_concepts, StatementType
```

Make sure `xbrl_concept_mapper.py` is configured with your API key and desired model.
Both mappers expose the same `batch_classify_concepts` and `StatementType` interface,
so no other code changes are required.

If you also run notebooks interactively, update their import cells the same way.
