// Configuration - Point to local Flask backend via nginx proxy
const API_ENDPOINT = '/api/analyze';

let fileContent = null;

// Handle file upload
document.getElementById('fileInput').addEventListener('change', function(e) {
    const file = e.target.files[0];
    if (file) {
        const reader = new FileReader();
        reader.onload = function(event) {
            fileContent = event.target.result;
            document.getElementById('rawInput').value = ''; // Clear textarea
        };
        reader.readAsText(file);
    } else {
        fileContent = null;
    }
});

async function analyzeAlert() {
    const statusDiv = document.getElementById('status');
    const resultsDiv = document.getElementById('results');
    const analyzeBtn = document.getElementById('analyzeBtn');
    const markdownOutput = document.getElementById('markdownOutput');
    
    // Get form values
    const textareaValue = document.getElementById('rawInput').value.trim();
    const payload = fileContent || textareaValue;
    
    if (!payload) {
        statusDiv.className = 'error';
        statusDiv.innerHTML = 'Please provide alert text or upload a file.';
        return;
    }
    
    const payloadType = document.querySelector('input[name="payloadType"]:checked').value;
    
    // Build request body
    const requestBody = {
        payload_type: payloadType,
        payload: payload
    };
    
    // Show analyzing status
    statusDiv.className = 'analyzing';
    statusDiv.innerHTML = '<span class="spinner"></span>Analyzing alert... This may take 30-60 seconds.';
    resultsDiv.classList.remove('visible');
    analyzeBtn.disabled = true;
    
    try {
        const response = await fetch(API_ENDPOINT, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(requestBody)
        });
        
        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.error || `HTTP ${response.status}: ${response.statusText}`);
        }
        
        const data = await response.json();
        
        // Show success status
        statusDiv.className = 'success';
        statusDiv.innerHTML = `Analysis completed successfully in ${data.meta.execution_time_seconds}s. Found ${data.meta.ttp_count} TTPs.`;
        
        // Render markdown
        markdownOutput.innerHTML = marked.parse(data.markdown);
        resultsDiv.classList.add('visible');
        
        // Scroll to results
        resultsDiv.scrollIntoView({ behavior: 'smooth', block: 'start' });
        
    } catch (error) {
        statusDiv.className = 'error';
        statusDiv.innerHTML = `Error: ${error.message}`;
        console.error('Analysis error:', error);
    } finally {
        analyzeBtn.disabled = false;
    }
}

// Allow Enter key in textarea (Ctrl+Enter to submit)
document.getElementById('rawInput').addEventListener('keydown', function(e) {
    if (e.ctrlKey && e.key === 'Enter') {
        analyzeAlert();
    }
});

