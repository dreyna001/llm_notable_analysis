# Notable Analysis - TTP Inference Project Outline

## 1. Purpose & Scope

**Goal**: Provide an intelligent TTP mapping system using advanced LLM capabilities for comprehensive analysis of security alerts with evidence-based validation and actionable investigation guidance.

**Approach**: LLM API → Structured prompt engineering → Complex JSON response parsing → Evidence-gated TTP analysis → Attack chain inference → Splunk enrichment queries.

**Key Advantages**:
- No training data required
- Adapts to new TTPs automatically
- Leverages LLM's reasoning capabilities for complex analysis
- Evidence-gated approach ensures high confidence
- Provides actionable investigation guidance
- Minimal maintenance overhead

## 2. Repository Structure

```
.
├── notable_analysis.py              # Main LLM-based TTP analysis implementation
├── enterprise_attack_v17.1_ids.json # Pre-extracted technique IDs (679 techniques)
├── extract_ttp_ids.py               # TTP ID extraction utility
├── generate_training_data.py        # Training data generation utilities
├── synthetic_logs.py                # Synthetic test cases for validation
├── test_ttp_validator.py            # TTPValidator testing suite
├── requirements.txt                 # Python dependencies
├── notable_analysis_outline.md      # This project outline
├── .env                            # Environment variables (API keys)
└── inference_results/               # Output files from analysis runs
    └── *.md                        # Markdown results with timestamps
```

## 3. Core Components

### TTPValidator Class
- **Purpose**: Validates MITRE ATT&CK technique IDs using pre-extracted data
- **Data Source**: `enterprise_attack_v17.1_ids.json` (679 curated techniques)
- **Methods**:
  - `_load_valid_ttps()`: Loads technique IDs from JSON file
  - `is_valid_ttp()`: Validates individual technique IDs
  - `filter_valid_ttps()`: Filters out invalid TTPs from LLM responses
  - `get_valid_ttps_for_prompt()`: Formats technique list for LLM prompt

### NotableTTPScorer Class (formerly GPT4TTPScorer)
- **format_alert_input()**: Combines summary, risk index, and raw log into structured text
- **analyze_ttp()**: Sends formatted alert to LLM and parses complex response
- **Error handling**: Robust handling of API failures and parsing errors
- **Response parsing**: Handles complex JSON with multiple analysis sections

### Input Format
```
[SUMMARY]
Human-readable description of the security event

[RISK INDEX]
Risk Score: 4
Source Product: WINEVENT
Threat Category: Initial Access

[RAW EVENT]
timestamp=2024-03-20T10:00:00 event_id=1234 process_name=powershell.exe ...
```

### Output Format (Complex JSON Structure)
```json
{
  "ttp_analysis": [
    {
      "ttp_id": "T1059.001",
      "ttp_name": "PowerShell",
      "confidence_score": 0.95,
      "explanation": "Clear evidence of PowerShell execution in the event log",
      "mitre_url": "https://attack.mitre.org/versions/v17/techniques/T1059/001/"
    }
  ],
  "attack_chain": {
    "likely_previous_steps": [...],
    "likely_next_steps": [...],
    "kill_chain_phase": "Execution"
  },
  "splunk_enrichment": [...]
}
```

## 4. LLM Configuration

### Model Settings
- **Model**: `o3-2025-04-16` (OpenAI's latest model)
- **Temperature**: 1 (for creative analysis)
- **Response Format**: Complex JSON object with structured analysis
- **System Prompt**: Cybersecurity expert specializing in MITRE ATT&CK analysis

### Advanced Prompt Engineering
- **Evidence-Gate Validation**: Only include techniques with direct evidence matches
- **Attack Chain Analysis**: Infer previous and next steps in attack lifecycle
- **Investigation Decision Trees**: Q1, Q2, Q3 with yes/no/unclear branches
- **Splunk Enrichment**: Actionable queries for investigation
- **Confidence Scoring**: Evidence-based confidence with uncertainty factors

## 5. Test Cases & Validation

### Synthetic Log Generation (`synthetic_logs.py`)
- **Windows Event Logs**: Event ID 4624, 4625, 7045, etc.
- **Network Security**: Firewall logs, IDS alerts, proxy logs
- **Endpoint Detection**: Process creation, file access, registry changes
- **Authentication Events**: Login attempts, privilege escalation, account changes

### MITRE ATT&CK Coverage
- **679 Technique IDs**: Comprehensive coverage from `enterprise_attack_v17.1_ids.json`
- **Parent Techniques**: 211 base techniques
- **Sub-techniques**: 468 specific variants
- **Tactic Coverage**: All 14 MITRE ATT&CK tactics

## 6. Usage Examples

### Basic Usage
```python
from notable_analysis import NotableTTPScorer

scorer = NotableTTPScorer()
alert_text = scorer.format_alert_input(summary, risk_index, raw_log)
scored_ttps = scorer.analyze_ttp(alert_text)
```

### Running Test Suite
```bash
python notable_analysis.py
```

### Testing TTPValidator
```bash
python test_ttp_validator.py
```

## 7. Performance Characteristics

### Speed
- **Per Alert**: 5-15 seconds (complex LLM analysis + processing)
- **Batch Processing**: Limited by API rate limits
- **Throughput**: ~4-12 alerts per minute

### Cost
- **Per API Call**: ~$0.02-0.05 (complex prompts and responses)
- **Monthly Estimate**: $200-800 for 10,000 alerts

### Accuracy
- **Precision**: Very High (evidence-gated approach)
- **Recall**: High (comprehensive technique coverage)
- **False Positives**: Very Low (evidence validation)

## 8. Error Handling

### API Failures
- Network connectivity issues
- Rate limit exceeded
- Authentication errors
- Model availability issues
- **Recovery**: Exponential backoff with retry logic

### Response Parsing
- Invalid JSON responses
- Unexpected response formats
- Missing required fields
- Malformed TTP IDs
- **Recovery**: Graceful degradation with logging

## 9. Security Considerations

### API Key Management
- Environment variable storage via `.env`
- Never commit to version control
- Rotation policies
- Access logging

### Data Privacy
- Log data handling
- PII detection and redaction
- Data retention policies
- Compliance considerations

### Rate Limiting
- Implement delays between calls
- Monitor usage patterns
- Alert on unusual activity
- Cost management

## 10. Deployment Options

### Local Development
```bash
# Setup environment
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows
pip install -r requirements.txt

# Set API key
export OPENAI_API_KEY="your_key_here"

# Run tests
python notable_analysis.py
```

### Docker Deployment
```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY notable_analysis.py .
COPY enterprise_attack_v17.1_ids.json .
CMD ["python", "notable_analysis.py"]
```

## 11. Monitoring & Observability

### Metrics to Track
- API call success rate
- Response times
- Cost per alert
- TTP detection accuracy
- Error rates by type
- Technique validation success rate

### Logging
- API call logs
- Error details
- Performance metrics
- Security events
- TTP validation results

## 12. Future Enhancements

### Short Term
- Multi-LLM support (Claude, Gemini, local models)
- Batch processing optimization
- Enhanced error recovery
- Cost optimization

### Medium Term
- Custom fine-tuning
- Integration with SIEM platforms
- Real-time streaming
- Advanced caching strategies

### Long Term
- Hybrid ML/LLM approach
- Continuous learning from feedback
- Advanced threat intelligence integration
- Automated response recommendations

## 13. Comparison with ML Version

| Aspect | Notable Analysis | ML Version |
|--------|------------------|------------|
| **Setup Complexity** | Low | High |
| **Training Required** | No | Yes |
| **Maintenance** | Minimal | Regular |
| **Cost Model** | Per-use | Upfront |
| **Accuracy** | Very High | High |
| **Speed** | 5-15s | <1s |
| **Flexibility** | Very High | Limited |
| **Offline Capability** | No | Yes |
| **Scalability** | API-limited | Hardware-limited |
| **Evidence Validation** | Built-in | Limited |
| **Investigation Guidance** | Comprehensive | Basic |

## 14. Development Workflow

### Code Quality
- Type hints throughout
- Comprehensive error handling
- Clear documentation
- Unit tests for core functions

### Testing Strategy
- Unit tests for TTPValidator
- Integration tests with mock API
- End-to-end tests with synthetic logs
- Performance benchmarking

### Documentation
- README with usage examples
- API documentation
- Troubleshooting guide
- Deployment instructions

## 15. Success Metrics

### Technical Metrics
- API call success rate > 99%
- Average response time < 10 seconds
- TTP detection accuracy > 95%
- False positive rate < 2%
- Technique validation success rate > 99%

### Business Metrics
- Cost per alert < $0.03
- User satisfaction > 4.8/5
- Time to deployment < 1 day
- Maintenance overhead < 1 hour/month

### Security Metrics
- Zero security incidents
- 100% API key security
- Complete audit trail
- Evidence-gated validation success
- Compliance with data protection regulations 