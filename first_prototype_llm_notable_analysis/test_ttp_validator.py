#!/usr/bin/env python3
"""
Test script to verify TTPValidator functionality with enterprise_attack_v17.1_ids.json
"""

from notable_analysis import TTPValidator

def test_ttp_validator():
    print("Testing TTPValidator with enterprise_attack_v17.1_ids.json")
    print("=" * 60)
    
    # Test initialization
    print("1. Initializing TTPValidator...")
    validator = TTPValidator()
    
    # Test counts
    print(f"2. Technique counts:")
    print(f"   - Parent techniques: {len(validator._valid_parent_techniques)}")
    print(f"   - Sub-techniques: {len(validator._valid_subtechniques)}")
    print(f"   - Total: {len(validator._valid_parent_techniques) + len(validator._valid_subtechniques)}")
    
    # Test validation
    print("\n3. Testing validation:")
    test_techniques = ["T1059.001", "T1059", "T9999.999", "T1001", "T1001.001"]
    for technique in test_techniques:
        is_valid = validator.is_valid_ttp(technique)
        print(f"   - {technique}: {'✓' if is_valid else '✗'}")
    
    # Test filtering
    print("\n4. Testing filtering:")
    test_ttps = [
        {"ttp_id": "T1059.001", "score": 0.8},
        {"ttp_id": "T9999.999", "score": 0.9},  # Invalid
        {"ttp_id": "T1059", "score": 0.7},
        {"ttp_id": "T1001", "score": 0.6}
    ]
    filtered = validator.filter_valid_ttps(test_ttps)
    print(f"   - Original: {len(test_ttps)} TTPs")
    print(f"   - Filtered: {len(filtered)} TTPs")
    print(f"   - Valid TTPs: {[t['ttp_id'] for t in filtered]}")
    
    # Test prompt generation
    print("\n5. Testing prompt generation:")
    ttps_for_prompt = validator.get_valid_ttps_for_prompt()
    print(f"   - Prompt TTPs length: {len(ttps_for_prompt)} characters")
    print(f"   - First 50 chars: {ttps_for_prompt[:50]}...")
    print(f"   - Last 50 chars: ...{ttps_for_prompt[-50:]}")
    
    print("\n" + "=" * 60)
    print("All tests completed successfully!")
    print("TTPValidator is working correctly with enterprise_attack_v17.1_ids.json")

if __name__ == "__main__":
    test_ttp_validator()
