#!/usr/bin/env python3
"""Quick test: recognize the sample CAPTCHA image using the recognizer module."""

import sys
sys.path.insert(0, "CloakBrowser")

from cloakbrowser.captcha.recognizer import recognize_captcha, CaptchaRecognition

IMAGE = "/Users/fofo/Library/Containers/com.tencent.qq/Data/Library/Application Support/QQ/nt_qq_6a719802a71b624b3b1fde8a5b3e2722/nt_data/Pic/2026-05/Ori/e266f839a2527632c71368c39e7bc774.png"

print("Testing CAPTCHA recognition...")
print(f"Image: {IMAGE}")
print()

result = recognize_captcha(IMAGE)

print(f"  is_captcha:       {result.is_captcha}")
print(f"  captcha_type:     {result.captcha_type}")
print(f"  category_text:    {result.category_text}")
print(f"  category_keyword: {result.category_keyword}")
print(f"  grid:             {result.grid_rows}×{result.grid_cols}")
print(f"  correct_cells:    {result.correct_cells} ({result.correct_count} cells)")
print(f"  incorrect_cells:  {result.incorrect_cells}")
print(f"  has_submit:       {result.has_submit_button}")
print(f"  has_refresh:      {result.has_refresh_button}")

# Validate
assert result.is_captcha, "Should detect as CAPTCHA"
assert result.captcha_type == "drag_grid", f"Expected drag_grid, got {result.captcha_type}"
assert result.correct_count == 6, f"Expected 6 correct cells, got {result.correct_count}"
assert len(result.incorrect_cells) == 3, f"Expected 3 incorrect cells, got {len(result.incorrect_cells)}"
assert result.grid_rows == 3 and result.grid_cols == 3, "Expected 3×3 grid"

# Verify specific cells — animals:
# Row 0: (0,0) parrot, (0,1) monkey, (0,2) panda → all correct
# Row 1: (1,0) peppers, (1,1) peppers → incorrect; (1,2) parrot → correct
# Row 2: (2,0) house → incorrect; (2,1) panda, (2,2) sheep → correct
expected_correct = {(0,0), (0,1), (0,2), (1,2), (2,1), (2,2)}
actual_correct = {tuple(c) for c in result.correct_cells}
assert actual_correct == expected_correct, f"Cell mismatch: {actual_correct} != {expected_correct}"

# Incorrect: (1,0) peppers, (1,1) peppers, (2,0) house
expected_incorrect = {(1,0), (1,1), (2,0)}
actual_incorrect = {tuple(c) for c in result.incorrect_cells}
assert actual_incorrect == expected_incorrect, f"Cell mismatch: {actual_incorrect} != {expected_incorrect}"

print()
print("✅ All assertions passed! Recognition works correctly.")
