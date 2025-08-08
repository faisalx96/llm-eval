'use client';

import React, { useState } from 'react';
import { useRouter } from 'next/navigation';
import { Button } from './button';
import { Modal } from './modal';
import { RunSelector } from './run-selector';

interface CompareButtonProps {
  runId?: string;
  variant?: 'default' | 'outline' | 'secondary';
  size?: 'sm' | 'md' | 'lg';
  className?: string;
}

export const CompareButton: React.FC<CompareButtonProps> = ({
  runId,
  variant = 'outline',
  size = 'sm',
  className = '',
}) => {
  const router = useRouter();
  const [showModal, setShowModal] = useState(false);
  const [compareWithRunId, setCompareWithRunId] = useState<string>('');

  const handleQuickCompare = () => {
    if (runId) {
      setShowModal(true);
    } else {
      // Navigate to compare page for selection
      router.push('/compare');
    }
  };

  const handleStartComparison = () => {
    if (runId && compareWithRunId) {
      router.push(`/compare?run1=${runId}&run2=${compareWithRunId}`);
      setShowModal(false);
    }
  };

  return (
    <>
      <Button
        variant={variant}
        size={size}
        onClick={handleQuickCompare}
        className={`mobile-touch-target ${className}`}
      >
        <svg className="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
        </svg>
        Compare
      </Button>

      {showModal && (
        <Modal 
          isOpen={showModal} 
          onClose={() => setShowModal(false)}
          title="Compare with Another Run"
        >
          <div className="space-y-4">
            <p className="text-neutral-600 dark:text-neutral-400">
              Select another run to compare with this evaluation.
            </p>
            
            <RunSelector
              selectedRunId={compareWithRunId}
              onRunSelect={setCompareWithRunId}
              excludeRunId={runId}
              label="Compare with"
              placeholder="Select a run to compare with..."
            />
            
            <div className="flex justify-end gap-2 pt-4">
              <Button
                variant="outline"
                onClick={() => setShowModal(false)}
              >
                Cancel
              </Button>
              <Button
                onClick={handleStartComparison}
                disabled={!compareWithRunId}
              >
                Start Comparison
              </Button>
            </div>
          </div>
        </Modal>
      )}
    </>
  );
};