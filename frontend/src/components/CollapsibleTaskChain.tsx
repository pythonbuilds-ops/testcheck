import React, { useState } from 'react';
import { ChevronDown, Wrench, CheckCircle, XCircle } from 'lucide-react';
import './CollapsibleTaskChain.css';

export interface TaskStep {
  id: string;
  type: 'status' | 'tool_call' | 'tool_result';
  message?: string;
  name?: string;
  args?: any;
  result?: any;
}

interface CollapsibleTaskChainProps {
  steps: TaskStep[];
  isComplete: boolean;
}

export const CollapsibleTaskChain: React.FC<CollapsibleTaskChainProps> = ({ steps, isComplete }) => {
  const [isOpen, setIsOpen] = useState(false);

  if (steps.length === 0) return null;

  // Get the latest meaningful status text to display
  const getLatestStatus = (): string => {
    for (let i = steps.length - 1; i >= 0; i--) {
      const step = steps[i];
      if (step.type === 'status' && step.message) return step.message;
      if (step.type === 'tool_call' && step.name) return `Using ${step.name}`;
      if (step.type === 'tool_result' && step.name) return `Completed ${step.name}`;
    }
    return 'Processing...';
  };

  const statusText = isComplete ? 'Done' : getLatestStatus();

  return (
    <div className="task-chain">
      {/* Inline shimmer status — click to expand */}
      <button className="task-status-text" onClick={() => setIsOpen(!isOpen)}>
        <span className={`status-label ${isComplete ? 'done' : 'running'}`}>
          {statusText}
        </span>
        <ChevronDown size={14} className={`expand-chevron ${isOpen ? 'rotated' : ''}`} />
      </button>

      {/* Expandable detail log */}
      <div className={`task-chain-body ${isOpen ? 'open' : ''}`}>
        <div className="chain-timeline">
          {steps.map((step, idx) => (
            <div key={step.id || idx} className={`chain-step step-${step.type}`}>
              <div className="step-content">
                {step.type === 'status' && (
                  <span className="step-status-msg">
                    <span className="step-icon">⟳</span> {step.message}
                  </span>
                )}
                {step.type === 'tool_call' && (
                  <div className="step-tool-call">
                    <Wrench size={12} className="step-wrench" />
                    <span className="tool-name">{step.name}</span>
                    {step.args && (
                      <span className="tool-args">
                        ({Object.entries(step.args).map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(', ')})
                      </span>
                    )}
                  </div>
                )}
                {step.type === 'tool_result' && (
                  <div className="step-tool-result">
                    {step.result?.success
                      ? <CheckCircle size={12} className="result-ok" />
                      : <XCircle size={12} className="result-fail" />}
                    <span className="result-text">
                      {(() => {
                        const txt = step.result?.result || JSON.stringify(step.result);
                        return typeof txt === 'string'
                          ? txt.substring(0, 120) + (txt.length > 120 ? '...' : '')
                          : 'Result returned';
                      })()}
                    </span>
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};
