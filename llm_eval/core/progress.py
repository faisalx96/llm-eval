"""Progress tracking and UI state management for evaluations."""

import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

@runtime_checkable
class ProgressObserver(Protocol):
    """Protocol for observing progress of evaluation items."""
    
    def start_item(self, index: int) -> None: ...
    
    def update_trace_info(self, index: int, trace_id: Optional[str], trace_url: Optional[str]) -> None: ...
    
    def update_output(self, index: int, output: Any) -> None: ...
    
    def set_metric_computing(self, index: int, metric: str) -> None: ...
    
    def update_metric(self, index: int, metric: str, value: Any, metadata: Optional[Dict[str, Any]] = None) -> None: ...
    
    def set_metric_error(self, index: int, metric: str) -> None: ...
    
    def complete_item(self, index: int) -> None: ...
    
    def fail_item(self, index: int, error: str) -> None: ...
    
    def fail_item_timeout(self, index: int, timeout: float) -> None: ...
    
    def get_snapshot(self) -> Dict[str, Any]: ...


class ProgressTracker(ProgressObserver):
    """Tracks the progress and state of evaluation items for the UI."""

    def __init__(self, items: List[Any], metrics: List[str]):
        self.items = items
        self.metrics = metrics
        self.item_statuses: Dict[int, Dict[str, Any]] = {}
        self._init_statuses()

    def _init_statuses(self):
        """Initialize status dictionaries for all items."""
        for idx, item in enumerate(self.items):
            input_text = str(item.input)
            expected_text = str(getattr(item, 'expected_output', 'N/A'))
        
            self.item_statuses[idx] = {
                'input': input_text,
                'output': '[dim]pending[/dim]',
                'expected': expected_text,
                'metrics': {metric: '[dim]pending[/dim]' for metric in self.metrics},
                'metric_meta': {metric: {} for metric in self.metrics},
                'status': 'pending',
                'time': '[dim]pending[/dim]',
                'start_time': None,
                'end_time': None,
                'trace_id': None,
                'trace_url': None
            }

    def start_item(self, index: int):
        """Mark an item as started."""
        self.item_statuses[index]['start_time'] = time.time()
        self.item_statuses[index]['status'] = 'in_progress'
        self.item_statuses[index]['time'] = '[yellow]running...[/yellow]'

    def update_trace_info(self, index: int, trace_id: Optional[str], trace_url: Optional[str]):
        """Update trace information for an item."""
        if trace_id:
            self.item_statuses[index]['trace_id'] = trace_id
        if trace_url:
            self.item_statuses[index]['trace_url'] = trace_url

    def update_output(self, index: int, output: Any):
        """Update the output for an item."""
        self.item_statuses[index]['output'] = str(output)

    def set_metric_computing(self, index: int, metric: str):
        """Mark a metric as computing."""
        self.item_statuses[index]['metrics'][metric] = '[yellow]computing...[/yellow]'

    def update_metric(self, index: int, metric: str, value: Any, metadata: Optional[Dict[str, Any]] = None):
        """Update a metric value and metadata."""
        # Format value for display
        display_val = str(value)
        if isinstance(value, bool):
            display_val = '✓' if value else '✗'
        elif isinstance(value, (int, float)):
            display_val = f"{int(value)}" if isinstance(value, int) or value.is_integer() else f"{value:.3f}"
        elif value is None:
            display_val = "None"
        
        # Truncate long strings
        if len(display_val) > 50:
            display_val = display_val[:50] + "..."

        self.item_statuses[index]['metrics'][metric] = display_val

        if metadata:
            try:
                self.item_statuses[index].setdefault('metric_meta', {})
                self.item_statuses[index]['metric_meta'].setdefault(metric, {})
                # Flatten metadata
                flat_meta = self._flatten_meta(metadata)
                for k, v in flat_meta.items():
                    self.item_statuses[index]['metric_meta'][metric][k] = v
            except Exception:
                pass

    def set_metric_error(self, index: int, metric: str):
        """Mark a metric as errored."""
        self.item_statuses[index]['metrics'][metric] = '[red]error[/red]'

    def complete_item(self, index: int):
        """Mark an item as completed."""
        end_time = time.time()
        start_time = self.item_statuses[index].get('start_time') or end_time
        elapsed = end_time - start_time
        
        self.item_statuses[index]['end_time'] = end_time
        self.item_statuses[index]['status'] = 'completed'
        self.item_statuses[index]['time'] = f"{int(elapsed)}s"

    def fail_item(self, index: int, error: str):
        """Mark an item as failed."""
        end_time = time.time()
        start_time = self.item_statuses[index].get('start_time') or end_time
        
        self.item_statuses[index]['end_time'] = end_time
        self.item_statuses[index]['status'] = 'error'
        self.item_statuses[index]['output'] = f'[red]error: {error[:30]}[/red]'
        self.item_statuses[index]['time'] = f"[red]{int(end_time - start_time)}s[/red]"
        
        for metric in self.metrics:
            self.item_statuses[index]['metrics'][metric] = '[red]N/A[/red]'

    def fail_item_timeout(self, index: int, timeout: float):
        """Mark an item as failed due to timeout."""
        end_time = time.time()
        start_time = self.item_statuses[index].get('start_time') or end_time
        
        self.item_statuses[index]['end_time'] = end_time
        self.item_statuses[index]['status'] = 'error'
        self.item_statuses[index]['output'] = '[red]timeout[/red]'
        self.item_statuses[index]['time'] = f"[red]{int(end_time - start_time)}s[/red]"
        
        for metric in self.metrics:
            self.item_statuses[index]['metrics'][metric] = '[red]N/A[/red]'

    def get_snapshot(self) -> Dict[str, Any]:
        """Generate a snapshot of the current state for the UI."""
        total_items = len(self.items)
        completed = sum(1 for s in self.item_statuses.values() if s['status'] == 'completed')
        in_progress = sum(1 for s in self.item_statuses.values() if s['status'] == 'in_progress')
        failed = sum(1 for s in self.item_statuses.values() if s['status'] == 'error')
        pending = total_items - completed - in_progress - failed
        success_rate = (completed / total_items * 100) if total_items > 0 else 0

        rows = []
        for idx in range(total_items):
            s = self.item_statuses[idx]
            rows.append(self._generate_row(idx, s))

        return {
            'rows': rows,
            'stats': {
                'total': total_items,
                'completed': completed,
                'in_progress': in_progress,
                'failed': failed,
                'pending': pending,
                'success_rate': success_rate,
            },
            'last_updated': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'metric_names': self.metrics,
        }

    def _generate_row(self, idx: int, s: Dict[str, Any]) -> Dict[str, Any]:
        """Generate a single row for the snapshot."""
        oval = self._strip_tags(s.get('output', ''))
        if oval == 'pending':
             # Keep consistent with original logic if needed, or just use stripped
             pass 
        
        tval = self._strip_tags(s.get('time', ''))
        
        mvals = []
        meta_block = {}
        for name in self.metrics:
            val = s['metrics'].get(name, '')
            # Handle specific UI states from original code if we want exact parity
            # But _strip_tags should handle [dim], [red], etc.
            mvals.append(self._strip_tags(val))
            
            try:
                meta_block[name] = {
                    k: str(v)
                    for k, v in (s.get('metric_meta', {}).get(name, {}) or {}).items()
                }
            except Exception:
                meta_block[name] = {}

        return {
            'index': idx,
            'status': s['status'],
            'input': str(s['input']),
            'input_full': str(s['input']),
            'output': oval,
            'output_full': str(s.get('output', '')),
            'expected': str(s['expected']),
            'expected_full': str(s['expected']),
            'metric_values': mvals,
            'metric_meta': meta_block,
            'time': tval,
            'latency_ms': int(
                ((s.get('end_time') or 0) - (s.get('start_time') or 0)) * 1000
            ) if s.get('end_time') and s.get('start_time') else None,
            'trace_id': s.get('trace_id'),
            'trace_url': s.get('trace_url'),
        }

    def _strip_tags(self, text: str) -> str:
        """Strip rich tags from text."""
        try:
            return (
                str(text)
                .replace('[dim]', '')
                .replace('[/dim]', '')
                .replace('[yellow]', '')
                .replace('[/yellow]', '')
                .replace('[red]', '')
                .replace('[/red]', '')
            )
        except Exception:
            return str(text)

    def _flatten_meta(self, md: Dict[str, Any]) -> Dict[str, Any]:
        """Flatten nested metadata dictionary."""
        flat = {}
        try:
            for k, v in (md or {}).items():
                if isinstance(v, dict):
                    for k2, v2 in v.items():
                        flat[f"{k}_{k2}"] = v2
                else:
                    flat[str(k)] = v
        except Exception:
            pass
        return flat
