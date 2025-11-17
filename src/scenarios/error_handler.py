"""
Centralized error handling and stack trace generation for scenario execution.

Provides comprehensive error information when scenario execution fails,
including full stack trace, execution context, and step details.
"""

import traceback
from typing import Any, Dict, Optional
from pathlib import Path


class ScenarioErrorReport:
    """Comprehensive error report for scenario execution failures."""
    
    def __init__(
        self,
        error: Exception,
        scenario_name: str,
        step_info: Optional[Dict[str, Any]] = None,
        context_summary: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize error report.
        
        Args:
            error: The exception that was raised
            scenario_name: Name of the scenario that failed
            step_info: Information about the failed step
            context_summary: Summary of execution context (variables, results, etc.)
        """
        self.error = error
        self.scenario_name = scenario_name
        self.step_info = step_info or {}
        self.context_summary = context_summary or {}
        self.stack_trace = traceback.format_exc()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert error report to dictionary."""
        return {
            "scenario": self.scenario_name,
            "error_type": type(self.error).__name__,
            "error_message": str(self.error),
            "step": self.step_info,
            "context": self.context_summary,
            "stack_trace": self.stack_trace
        }
    
    def format_for_display(self) -> str:
        """Format error report for human-readable display."""
        lines = []
        lines.append("=" * 80)
        lines.append("SCENARIO EXECUTION ERROR")
        lines.append("=" * 80)
        lines.append(f"Scenario: {self.scenario_name}")
        lines.append(f"Error Type: {type(self.error).__name__}")
        lines.append(f"Error Message: {self.error}")
        lines.append("")
        
        if self.step_info:
            lines.append("Failed Step:")
            for key, value in self.step_info.items():
                lines.append(f"  {key}: {value}")
            lines.append("")
        
        if self.context_summary:
            lines.append("Execution Context:")
            lines.append(f"  Total Steps: {self.context_summary.get('total_steps', 'unknown')}")
            lines.append(f"  Passed: {self.context_summary.get('passed', 'unknown')}")
            lines.append(f"  Failed: {self.context_summary.get('failed', 'unknown')}")
            lines.append(f"  Duration: {self.context_summary.get('duration_seconds', 'unknown')}s")
            
            if 'variables' in self.context_summary:
                lines.append(f"  Variables: {list(self.context_summary['variables'].keys())}")
            lines.append("")
        
        lines.append("Stack Trace:")
        lines.append(self.stack_trace)
        lines.append("=" * 80)
        
        return "\n".join(lines)
    
    def save_to_file(self, log_dir: Path) -> Path:
        """
        Save error report to a file.
        
        Args:
            log_dir: Directory to save the error report
            
        Returns:
            Path to the created error report file
        """
        log_dir.mkdir(parents=True, exist_ok=True)
        
        import time
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        filename = f"scenario_error_{self.scenario_name}_{timestamp}.txt"
        filepath = log_dir / filename
        
        with open(filepath, 'w') as f:
            f.write(self.format_for_display())
        
        return filepath


def create_error_report(
    error: Exception,
    scenario_name: str,
    current_step: Optional[Any] = None,
    context: Optional[Any] = None
) -> ScenarioErrorReport:
    """
    Create a comprehensive error report for scenario execution failure.
    
    Args:
        error: The exception that was raised
        scenario_name: Name of the scenario
        current_step: Current step that was being executed (if any)
        context: RuntimeContext object (if available)
        
    Returns:
        ScenarioErrorReport instance
    """
    step_info = {}
    if current_step:
        step_info = {
            "type": type(current_step).__name__,
            "details": str(current_step)[:200]  # Limit to 200 chars
        }
        
        # Try to extract specific step attributes
        for attr in ['cli', 'rpc', 'docker_op', 'wait', 'node']:
            if hasattr(current_step, attr):
                step_info[attr] = getattr(current_step, attr)
    
    context_summary = {}
    if context:
        try:
            summary = context.get_summary()
            context_summary = summary
            context_summary['variables'] = list(context.variables.keys())
        except Exception:
            # If summary fails, just continue without it
            pass
    
    return ScenarioErrorReport(
        error=error,
        scenario_name=scenario_name,
        step_info=step_info,
        context_summary=context_summary
    )

