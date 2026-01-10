"""
Backend service for Notable Analysis.

Flask app that invokes Bedrock Nova Pro for TTP analysis.
"""

import json
import os
import sys
import time
import logging
from pathlib import Path
from flask import Flask, request, jsonify
from flask_cors import CORS

# Add current directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from ttp_analyzer import BedrockAnalyzer
from markdown_generator import generate_markdown_report

app = Flask(__name__)
CORS(app)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def normalize_alert(request_body):
    """Normalize incoming request into internal alert structure.
    
    Args:
        request_body: Dict containing payload and payload_type.
        
    Returns:
        Dict with normalized alert containing summary, risk_index, and raw_log.
    """
    payload_type = request_body.get('payload_type', 'raw_text')
    payload = request_body.get('payload', '')
    
    summary = ""
    risk_index = {
        "risk_score": "N/A",
        "source_product": "N/A",
        "threat_category": "N/A"
    }
    raw_log = {}
    
    if payload_type == "raw_json":
        try:
            parsed_json = json.loads(payload)
            if isinstance(parsed_json, dict):
                summary = "User-submitted JSON alert"
                raw_log = parsed_json
            else:
                summary = payload[:400] if len(payload) > 400 else payload
                raw_log = {"raw_event": payload}
        except json.JSONDecodeError:
            logger.info("Failed to parse payload as JSON, treating as raw text")
            summary = payload[:400] if len(payload) > 400 else payload
            raw_log = {"raw_event": payload}
    else:
        summary = payload[:400] if len(payload) > 400 else payload
        raw_log = {"raw_event": payload}
    
    return {
        "summary": summary,
        "risk_index": risk_index,
        "raw_log": raw_log
    }


@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint for ECS.
    
    Returns:
        JSON response with status 'healthy' and HTTP 200.
    """
    return jsonify({'status': 'healthy'}), 200


@app.route('/api/analyze', methods=['POST'])
def analyze():
    """Analyze security alert using Bedrock Nova Pro.
    
    Receives alert data from frontend, normalizes it, calls Bedrock for TTP
    analysis, and returns markdown report with structured data.
    
    Expected JSON body:
        payload (str): Alert text or JSON string.
        payload_type (str): Either 'raw_text' or 'raw_json'.
        
    Returns:
        JSON response with markdown report, LLM response, scored TTPs, and
        execution metadata. HTTP 200 on success, 400/500 on error.
    """
    start_time = time.time()
    
    try:
        # Get request data from frontend
        frontend_data = request.get_json()
        
        if not frontend_data:
            return jsonify({'error': 'No JSON body provided'}), 400
        
        # Validate required fields
        if 'payload' not in frontend_data or not frontend_data['payload']:
            return jsonify({'error': "Missing or empty 'payload' field"}), 400
        
        payload_type = frontend_data.get('payload_type', 'raw_text')
        if payload_type not in ['raw_text', 'raw_json']:
            return jsonify({'error': "Invalid payload_type. Must be 'raw_text' or 'raw_json'"}), 400
        
        # Normalize the alert
        logger.info("Normalizing alert input")
        alert_obj = normalize_alert(frontend_data)
        
        # Initialize analyzer
        model_id = os.environ.get('BEDROCK_MODEL_ID', 'amazon.nova-pro-v1:0')
        logger.info(f"Initializing analyzer with model: {model_id}")
        analyzer = BedrockAnalyzer(model_id=model_id)
        
        # Format alert text
        alert_text = analyzer.format_alert_input(
            alert_obj['summary'],
            alert_obj['risk_index'],
            alert_obj['raw_log']
        )
        
        # Run analysis
        logger.info("Starting TTP analysis")
        scored_ttps = analyzer.analyze_ttp(alert_text)
        
        # Get the full LLM response
        llm_response = analyzer.last_llm_response or {}
        
        # If there was a parsing error, return raw content
        if "raw_error" in llm_response:
            return jsonify({
                "markdown": f"## Raw Model Response\n\n```\n{llm_response['raw_error']}\n```",
                "llm_response": llm_response,
                "scored_ttps": [],
                "meta": {
                    "model_id": model_id,
                    "execution_time_seconds": round(time.time() - start_time, 2),
                    "ttp_count": 0,
                    "error": "Failed to parse JSON from model"
                }
            }), 200
        
        # Generate markdown report
        logger.info("Generating markdown report")
        markdown = generate_markdown_report(alert_text, llm_response, scored_ttps)
        
        # Build response
        end_time = time.time()
        response_data = {
            "markdown": markdown,
            "llm_response": llm_response,
            "scored_ttps": scored_ttps,
            "meta": {
                "model_id": model_id,
                "execution_time_seconds": round(end_time - start_time, 2),
                "ttp_count": len(scored_ttps)
            }
        }
        
        logger.info(f"Analysis completed successfully in {end_time - start_time:.2f} seconds")
        return jsonify(response_data), 200
        
    except Exception as e:
        logger.error(f"Unexpected error in analyze: {str(e)}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        
        return jsonify({
            'error': 'Internal server error',
            'message': str(e)
        }), 500


if __name__ == '__main__':
    # In ECS, use gunicorn: gunicorn -w 2 -b 0.0.0.0:8080 backend_example:app
    app.run(host='0.0.0.0', port=8080, debug=False)

