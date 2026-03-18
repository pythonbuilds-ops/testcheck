"""
Vision Pipeline — Screen capture and visual analysis via Llama 4 Scout.

Used as a fallback when the accessibility tree is insufficient,
for visual verification of actions, and for understanding
complex UI layouts.
"""

from typing import Optional, Dict, Any


class VisionAnalyzer:
    """Screen analysis using the Llama 4 Scout vision model."""

    def __init__(self, adb_controller, model_manager):
        """
        Args:
            adb_controller: ADBController instance.
            model_manager: ModelManager instance.
        """
        self.adb = adb_controller
        self.models = model_manager

    def capture_and_analyze(
        self,
        prompt: str = "Describe what is on this screen. List all visible UI elements, buttons, text fields, and their approximate positions.",
        max_width: int = 540,
        quality: int = 50,
    ) -> Dict[str, Any]:
        """
        Screenshot the device and analyze with the vision model.

        Args:
            prompt: Question or instruction about the screen.
            max_width: Max image width (smaller = fewer tokens).
            quality: JPEG quality for compression.

        Returns:
            Dict with 'description' (str) and 'success' (bool).
        """
        try:
            img_b64 = self.adb.screenshot_base64(
                max_width=max_width, quality=quality
            )

            description = self.models.see(
                image_base64=img_b64,
                prompt=prompt,
                system=(
                    "You are a phone screen analyzer. Describe the UI precisely. "
                    "List visible elements: buttons, text, input fields, icons, tabs. "
                    "Mention their approximate screen position (top/middle/bottom, left/center/right). "
                    "Be concise but comprehensive."
                ),
            )

            return {"success": True, "description": description}
        except Exception as e:
            return {"success": False, "description": f"Vision error: {str(e)}"}

    def identify_elements(
        self,
        focus: str = "interactive elements",
        max_width: int = 540,
    ) -> Dict[str, Any]:
        """
        Identify specific UI elements on screen.

        Args:
            focus: What to focus on (e.g., 'buttons', 'text fields', 'icons').

        Returns:
            Dict with element descriptions.
        """
        prompt = (
            f"Focus on identifying {focus} on this screen. "
            f"For each element, describe: what it is, what text/icon it shows, "
            f"and approximately where it is on screen (use quadrants or relative positions). "
            f"Format as a numbered list."
        )
        return self.capture_and_analyze(prompt=prompt, max_width=max_width)

    def verify_action(
        self,
        expected_result: str,
        max_width: int = 540,
    ) -> Dict[str, Any]:
        """
        Verify that a previous action had the expected result.

        Args:
            expected_result: What should be visible on screen after the action.

        Returns:
            Dict with 'verified' (bool), 'description' (str).
        """
        prompt = (
            f"Look at this screen and determine: {expected_result}\n"
            f"Answer with YES or NO first, then briefly explain what you see."
        )
        result = self.capture_and_analyze(prompt=prompt, max_width=max_width)

        if result["success"]:
            desc = result["description"].lower()
            verified = desc.startswith("yes") or "yes" in desc[:50]
            result["verified"] = verified
        else:
            result["verified"] = False

        return result

    def read_screen_text(self, max_width: int = 720) -> Dict[str, Any]:
        """
        Extract all readable text from the current screen.

        Returns:
            Dict with 'text' containing all visible text.
        """
        prompt = (
            "Extract ALL readable text from this screen exactly as shown. "
            "Include button labels, titles, body text, hints, and any other visible text. "
            "Preserve the layout order (top to bottom, left to right). "
            "Do not add any commentary, just list the text."
        )
        result = self.capture_and_analyze(prompt=prompt, max_width=max_width, quality=70)
        result["text"] = result.get("description", "")
        return result

    def compare_screens(
        self,
        before_b64: str,
        after_b64: str,
        action_taken: str,
    ) -> Dict[str, Any]:
        """
        Compare two screenshots to verify an action's effect.

        Args:
            before_b64: Base64 screenshot before action.
            after_b64: Base64 screenshot after action.
            action_taken: Description of action that was performed.

        Returns:
            Dict with comparison analysis.
        """
        # Since we can only send one image per request, analyze the after screenshot
        # with context about what was expected
        prompt = (
            f"An action was just performed: '{action_taken}'. "
            f"Look at the current screen state and determine if the action was successful. "
            f"Describe what you see and whether it matches the expected outcome."
        )
        try:
            description = self.models.see(
                image_base64=after_b64,
                prompt=prompt,
                system="You are verifying whether a phone action succeeded by analyzing the screen.",
            )
            return {"success": True, "analysis": description}
        except Exception as e:
            return {"success": False, "analysis": f"Comparison error: {str(e)}"}
