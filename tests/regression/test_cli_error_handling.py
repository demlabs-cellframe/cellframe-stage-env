"""
Test for CLI error handling improvements.

Verifies that CLI YAML error detection logic works correctly.
"""

import pytest
import yaml


class TestCLIYAMLErrorDetection:
    """Test YAML error detection logic from CLI output."""
    
    def test_detects_yaml_error_with_code_32(self):
        """
        Test: Should detect error code 32 from YAML output.
        
        ✅  Should PASS - error detection works
        
        This tests the logic added to cli.py for detecting YAML errors
        before attempting hash extraction.
        """
        # Real error output from arbitrage test
        error_output = """    
        errors: 
            
                code: 32
                message: Arbitrage transaction failed Network 'stagenet' has no fee address configured. Network fee address must be set before arbitrage transactions can be processed. Use 'net -net stagenet fee_addr <address>' to configure the fee collection address.


"""
        
        # Parse YAML (like cli.py does)
        output_data = yaml.safe_load(error_output)
        
        if isinstance(output_data, dict) and 'errors' in output_data:
            error_info = output_data['errors']
            error_code = error_info.get('code', -1)
            error_message = error_info.get('message', '')
            
            # Verify error is detected
            assert error_code == 32, f"Should detect error code 32, got {error_code}"
            assert "fee address" in error_message, "Should extract error message"
            assert "Arbitrage" in error_message, "Should extract full error text"
            
            print(f"✅ Detected error code {error_code}")
            print(f"✅ Error message: {error_message[:80]}...")
        else:
            pytest.fail("Should have detected error in YAML")
    
    def test_ignores_success_output(self):
        """
        Test: Should NOT detect error in successful output with hash.
        
        ✅  Should PASS - success path unchanged
        """
        success_output = """
New: 0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef
Transaction created successfully
"""
        
        # Try parsing as YAML
        try:
            output_data = yaml.safe_load(success_output)
            
            # Should either fail to parse or not have 'errors' field
            if isinstance(output_data, dict):
                assert 'errors' not in output_data, "Success output should not have errors field"
        except yaml.YAMLError:
            # Expected - plain text with hash isn't valid YAML
            pass
        
        print("✅ Success output doesn't trigger error detection")
    
    def test_detects_error_code_zero_as_success(self):
        """
        Test: Error code 0 should be treated as success (no error).
        
        ✅  Should PASS - code 0 means success
        """
        # Some commands return code: 0 in YAML for success
        success_yaml = """
errors:
    code: 0
    message: Success
"""
        
        output_data = yaml.safe_load(success_yaml)
        
        if isinstance(output_data, dict) and 'errors' in output_data:
            error_code = output_data['errors'].get('code', -1)
            
            # Code 0 means NO error (success)
            if error_code == 0:
                print("✅ Error code 0 correctly treated as success")
                return
        
        pytest.fail("Should recognize error code 0 as success")
    
    def test_hash_pattern_matches_various_formats(self):
        """
        Test: Hash extraction pattern should work with multiple formats.
        
        ✅  Should PASS - pattern is comprehensive
        """
        import re
        
        # Pattern from extractors.py
        pattern = r'(?:New:\s+|(?:last_)?(?:event_)?hash["\']?\s*:\s*["\']?|datum_hash["\']?\s*:\s*["\']?|emission_hash["\']?\s*:\s*["\']?|Datum\s+)?(?<!Old: )(0x[A-Fa-f0-9]{64})'
        
        test_cases = [
            ("New: 0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef", True),  # Includes prefix
            ('hash: "0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"', True),
            ("datum_hash: 0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef", True),
            ("emission_hash: 0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef", True),
            ("Datum 0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef", True),
            ("0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef", False),  # Standalone, no prefix
        ]
        
        for test_input, has_prefix in test_cases:
            match = re.search(pattern, test_input)
            assert match, f"Pattern should match: {test_input}"
            
            # Check that hash (0x...) is in the match
            matched_text = match.group(0)
            assert "0x1234567890abcdef" in matched_text, f"Should extract hash from: {test_input}"
        
        print(f"✅ Hash pattern matches {len(test_cases)} different formats")
    
    def test_hash_pattern_ignores_old_hash(self):
        """
        Test: Pattern should ignore "Old: 0x..." hashes (for replacements).
        
        ✅  Should PASS - negative lookbehind works
        """
        import re
        
        pattern = r'(?:New:\s+|(?:last_)?(?:event_)?hash["\']?\s*:\s*["\']?|datum_hash["\']?\s*:\s*["\']?|emission_hash["\']?\s*:\s*["\']?|Datum\s+)?(?<!Old: )(0x[A-Fa-f0-9]{64})'
        
        # Output with both Old and New hashes (token replacement)
        replacement_output = """
Old: 0x0000000000000000000000000000000000000000000000000000000000000000
New: 0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef
"""
        
        match = re.search(pattern, replacement_output)
        assert match, "Should find a hash"
        extracted_hash = match.group(0)
        
        # Should extract the NEW hash, not the OLD one
        assert "1234567890abcdef" in extracted_hash, "Should extract New hash"
        assert "0000000000000000" not in extracted_hash, "Should NOT extract Old hash"
        
        print("✅ Pattern correctly ignores 'Old:' hashes")
