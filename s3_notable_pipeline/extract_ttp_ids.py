import json
import pandas as pd
import requests
from io import BytesIO
import time

# Download the v17.1 Excel from MITRE's site
# Using direct link from MITRE's attack site for Enterprise ATT&CK v17.1 techniques
url = "https://attack.mitre.org/docs/enterprise-attack-v17.1/enterprise-attack-v17.1-techniques.xlsx"

# Retry logic for download
max_retries = 3
retry_delay = 5
response = None

for attempt in range(max_retries):
    try:
        print(f"Downloading ATT&CK data (attempt {attempt + 1}/{max_retries})...")
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        print(f"Download successful ({len(response.content)} bytes)")
        break
    except requests.RequestException as e:
        print(f"Download failed: {e}")
        if attempt < max_retries - 1:
            print(f"Retrying in {retry_delay} seconds...")
            time.sleep(retry_delay)
        else:
            print("Max retries reached. Exiting.")
            raise

# Load Excel into pandas
print("Parsing Excel data...")
xls = pd.read_excel(BytesIO(response.content))

# Extract technique IDs (parents + sub-techniques), ignoring revoked/deprecated as they are not in the techniques sheet
ids = xls['ID'].dropna().astype(str).str.strip().tolist()
ids = [i for i in ids if i.startswith('T')]

# Validation: ensure we have a reasonable number of IDs
if len(ids) < 100:
    raise ValueError(f"Extracted only {len(ids)} technique IDs - expected at least 100. Data may be incomplete.")

print(f"Extracted {len(ids)} technique IDs")

# Sort: parents first, then sub-techniques
parents = sorted([i for i in ids if '.' not in i])
subs = sorted([i for i in ids if '.' in i])
ordered_ids = parents + subs

print(f"  - {len(parents)} parent techniques")
print(f"  - {len(subs)} sub-techniques")

# Save to JSON
output_path = "enterprise_attack_v17.1_ids.json"
with open(output_path, "w") as f:
    json.dump(ordered_ids, f, indent=2)

print(f"Saved to {output_path}")
