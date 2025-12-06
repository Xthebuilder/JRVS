# JARVIS Custom Ollama Model

Custom Ollama model based on **DeepSeek-R1:14B** with JARVIS personality and capabilities.

## What is JARVIS?

**JARVIS** (Just A Rather Very Intelligent System) is a custom-tuned AI model that:

- 🎩 Has a sophisticated, professional personality (inspired by Tony Stark's AI)
- 🧠 Knows about all JRVS capabilities (JARCORE, RAG, Data Analysis, Calendar)
- 💻 Specialized for coding, data analysis, and productivity tasks
- 🤖 Proactive and context-aware
- 🎯 Optimized parameters for technical work

## Quick Start

### Create the JARVIS Model

```bash
cd /home/xmanz/JRVS
./create_jarvis_model.sh
```

This will:
1. Check for DeepSeek-R1:14B (pulls if needed)
2. Build JARVIS model from Modelfile
3. Test the model

### Use JARVIS

**In terminal:**
```bash
ollama run jarvis
```

**In JRVS:**
1. Start web server: `python3 web_server.py`
2. Go to settings
3. Switch model to "jarvis"

## Model Details

### Base Model
- **DeepSeek-R1:14B** - Reasoning-focused model
- ~8GB download
- Strong coding and analytical capabilities

### Custom Configuration

**System Prompt:**
- JARVIS personality and identity
- Knowledge of JRVS capabilities
- Professional, proactive behavior
- British wit and sophistication

**Parameters:**
- Temperature: 0.7 (balanced creativity/precision)
- Context: 4096 tokens
- Top-P: 0.9
- Repeat penalty: 1.1

### JARVIS Personality

**Professional:**
- Precise technical responses
- Proactive suggestions
- Anticipates user needs

**JARVIS Touch:**
- Slightly British wit
- Sophisticated demeanor
- Occasional "Sir" when appropriate
- Calm and composed

## Comparison

| Model | Best For | Personality | Speed |
|-------|----------|-------------|-------|
| **jarvis** | JRVS tasks, coding, data | JARVIS persona | Medium |
| deepseek-r1:14b | General reasoning | Neutral | Medium |
| deepseek-coder:6.7b | Pure coding | Neutral | Fast |
| llama3.1:8b | General chat | Neutral | Fast |

## Example Interactions

### Standard DeepSeek-R1:
```
User: Analyze my data
AI: I'll analyze your data. Please provide the dataset.
```

### JARVIS:
```
User: Analyze my data
JARVIS: Certainly, sir. I'll access the Data Analysis Lab to examine your dataset.
Which file would you like me to analyze? I can handle CSV or Excel formats, and
I'll provide comprehensive insights including data quality assessment, statistical
analysis, and AI-generated recommendations.
```

## When to Use JARVIS

✅ **Use JARVIS when:**
- Working within JRVS ecosystem
- Need proactive assistance
- Want personality + capability awareness
- Doing coding, data analysis, or productivity tasks

⚠️ **Use other models when:**
- Need fastest possible responses (use smaller models)
- Want pure technical output without personality
- Working outside JRVS context

## Customization

Edit `Modelfile.jarvis` to customize:

**Change personality:**
```
SYSTEM """
You are JARVIS, but more formal/casual/funny...
"""
```

**Adjust parameters:**
```
PARAMETER temperature 0.5    # More precise
PARAMETER temperature 0.9    # More creative
PARAMETER num_ctx 8192       # Larger context window
```

**Rebuild after changes:**
```bash
ollama create jarvis -f Modelfile.jarvis
```

## Testing JARVIS

### Quick Test
```bash
ollama run jarvis "Hello JARVIS, introduce yourself and tell me what you can do"
```

### Coding Test
```bash
ollama run jarvis "Generate a Python function to calculate factorial with error handling"
```

### JRVS Integration Test
```bash
ollama run jarvis "What tools do you have access to in JRVS?"
```

## Advanced Usage

### Use in Python
```python
import ollama

response = ollama.chat(model='jarvis', messages=[
    {
        'role': 'user',
        'content': 'Analyze this code for issues: [code here]'
    }
])

print(response['message']['content'])
```

### Use in JRVS Config
```python
# config.py
DEFAULT_MODEL = "jarvis"
```

### API Usage
```bash
curl http://localhost:11434/api/generate -d '{
  "model": "jarvis",
  "prompt": "What capabilities do you have?"
}'
```

## Model Management

**List models:**
```bash
ollama list
```

**Show JARVIS details:**
```bash
ollama show jarvis
```

**Delete JARVIS:**
```bash
ollama rm jarvis
```

**Recreate JARVIS:**
```bash
./create_jarvis_model.sh
```

## Performance

- **Model Size:** ~8GB (same as DeepSeek-R1:14B base)
- **Memory Usage:** ~16GB RAM recommended
- **Speed:** Similar to base DeepSeek-R1:14B
- **GPU:** Works with CPU, faster with GPU (CUDA/ROCm)

## Troubleshooting

**"Model not found":**
```bash
ollama list | grep jarvis
# If not found, recreate:
./create_jarvis_model.sh
```

**"Out of memory":**
- Close other applications
- Use smaller model (deepseek-coder:6.7b)
- Or use quantized version: `FROM deepseek-r1:14b-q4`

**Model behaves unexpectedly:**
- Check `Modelfile.jarvis` for errors
- Rebuild: `ollama create jarvis -f Modelfile.jarvis`

## Files

- `Modelfile.jarvis` - Model definition and system prompt
- `create_jarvis_model.sh` - Automated setup script
- `JARVIS_MODEL.md` - This documentation

## Credits

- **Base Model:** DeepSeek-R1:14B by DeepSeek AI
- **System:** JRVS (JARVIS) AI Agent
- **Inspiration:** Tony Stark's JARVIS from Marvel/MCU

---

**Meet JARVIS - Your sophisticated AI assistant powered by DeepSeek-R1!** 🤖✨
