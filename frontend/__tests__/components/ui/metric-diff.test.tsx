import React from 'react'
import { render, screen } from '../../utils/test-utils'
import { MetricDiff } from '@/components/ui/metric-diff'

describe('MetricDiff Component', () => {
  const defaultProps = {
    metricName: 'exact_match',
    run1Score: 0.85,
    run2Score: 0.90,
    difference: 0.05,
    percentageChange: 5.88,
    direction: 'better' as const,
  }

  describe('Basic Rendering', () => {
    it('renders metric name and scores correctly', () => {
      render(<MetricDiff {...defaultProps} />)

      expect(screen.getByText('exact_match')).toBeInTheDocument()
      expect(screen.getByText('85.0%')).toBeInTheDocument() // Run 1 score
      expect(screen.getByText('90.0%')).toBeInTheDocument() // Run 2 score
      expect(screen.getByText('+5.0pp')).toBeInTheDocument() // Difference
      expect(screen.getByText('+5.9% change')).toBeInTheDocument() // Percentage change
    })

    it('renders all section labels', () => {
      render(<MetricDiff {...defaultProps} />)

      expect(screen.getByText('Run 1')).toBeInTheDocument()
      expect(screen.getByText('Run 2')).toBeInTheDocument()
      expect(screen.getByText('Change')).toBeInTheDocument()
    })
  })

  describe('Score Formatting', () => {
    it('formats scores between 0-1 as percentages', () => {
      render(
        <MetricDiff
          {...defaultProps}
          run1Score={0.756}
          run2Score={0.892}
        />
      )

      expect(screen.getByText('75.6%')).toBeInTheDocument()
      expect(screen.getByText('89.2%')).toBeInTheDocument()
    })

    it('formats scores above 1 as decimals', () => {
      render(
        <MetricDiff
          {...defaultProps}
          run1Score={1.234}
          run2Score={2.567}
        />
      )

      expect(screen.getByText('1.234')).toBeInTheDocument()
      expect(screen.getByText('2.567')).toBeInTheDocument()
    })

    it('handles zero scores correctly', () => {
      render(
        <MetricDiff
          {...defaultProps}
          run1Score={0.0}
          run2Score={0.0}
        />
      )

      // There should be two instances of 0.0% (one for each run)
      const zeroScores = screen.getAllByText('0.0%')
      expect(zeroScores).toHaveLength(2)
    })
  })

  describe('Difference Formatting', () => {
    it('formats percentage point differences correctly', () => {
      render(
        <MetricDiff
          {...defaultProps}
          difference={0.156}
        />
      )

      expect(screen.getByText('+15.6pp')).toBeInTheDocument()
    })

    it('formats negative differences correctly', () => {
      render(
        <MetricDiff
          {...defaultProps}
          difference={-0.034}
          direction="worse"
        />
      )

      expect(screen.getByText('-3.4pp')).toBeInTheDocument()
    })

    it('formats large numeric differences correctly', () => {
      render(
        <MetricDiff
          {...defaultProps}
          difference={2.456}
          run1Score={10.123}
          run2Score={12.579}
        />
      )

      expect(screen.getByText('+2.456')).toBeInTheDocument()
    })
  })

  describe('Direction Indicators', () => {
    it('shows improvement icon for better direction', () => {
      render(<MetricDiff {...defaultProps} direction="better" />)

      const diffText = screen.getByText('+5.0pp')
      const diffContainer = diffText.closest('div')
      expect(diffContainer?.className).toContain('text-success-600')

      // Check for SVG icon (improvement arrow)
      const svg = diffContainer?.querySelector('svg')
      expect(svg).toBeInTheDocument()
      expect(svg).toHaveAttribute('viewBox', '0 0 24 24')
    })

    it('shows decline icon for worse direction', () => {
      render(
        <MetricDiff
          {...defaultProps}
          direction="worse"
          difference={-0.05}
          percentageChange={-5.88}
        />
      )

      const diffText = screen.getByText('-5.0pp')
      const diffContainer = diffText.closest('div')
      expect(diffContainer?.className).toContain('text-danger-600')
    })

    it('shows neutral icon for neutral direction', () => {
      render(
        <MetricDiff
          {...defaultProps}
          direction="neutral"
          difference={0.00}
          percentageChange={0.0}
        />
      )

      const diffText = screen.getByText('+0.0pp')
      const diffContainer = diffText.closest('div')
      expect(diffContainer?.className).toContain('text-neutral-600')
    })
  })

  describe('Statistical Significance', () => {
    it('shows significance badge when is_significant is true', () => {
      render(
        <MetricDiff
          {...defaultProps}
          isSignificant={true}
        />
      )

      expect(screen.getByText('Significant')).toBeInTheDocument()
    })

    it('does not show significance badge when is_significant is false', () => {
      render(
        <MetricDiff
          {...defaultProps}
          isSignificant={false}
        />
      )

      expect(screen.queryByText('Significant')).not.toBeInTheDocument()
    })

    it('displays p-value when provided', () => {
      render(
        <MetricDiff
          {...defaultProps}
          pValue={0.0234}
        />
      )

      expect(screen.getByText('p = 0.0234')).toBeInTheDocument()
    })

    it('displays confidence interval when provided', () => {
      render(
        <MetricDiff
          {...defaultProps}
          confidenceInterval={[0.012, 0.088]}
        />
      )

      expect(screen.getByText('95% CI: [0.012, 0.088]')).toBeInTheDocument()
    })
  })

  describe('Percentage Change Display', () => {
    it('shows positive percentage change correctly', () => {
      render(
        <MetricDiff
          {...defaultProps}
          percentageChange={12.34}
        />
      )

      expect(screen.getByText('+12.3% change')).toBeInTheDocument()
    })

    it('shows negative percentage change correctly', () => {
      render(
        <MetricDiff
          {...defaultProps}
          percentageChange={-8.76}
        />
      )

      expect(screen.getByText('-8.8% change')).toBeInTheDocument()
    })

    it('handles zero percentage change', () => {
      render(
        <MetricDiff
          {...defaultProps}
          percentageChange={0.0}
        />
      )

      expect(screen.getByText('+0.0% change')).toBeInTheDocument()
    })
  })

  describe('Complex Scenarios', () => {
    it('renders complete statistical analysis', () => {
      render(
        <MetricDiff
          {...defaultProps}
          isSignificant={true}
          pValue={0.0045}
          confidenceInterval={[0.023, 0.077]}
        />
      )

      expect(screen.getByText('Significant')).toBeInTheDocument()
      expect(screen.getByText('p = 0.0045')).toBeInTheDocument()
      expect(screen.getByText('95% CI: [0.023, 0.077]')).toBeInTheDocument()
    })

    it('applies custom className', () => {
      const { container } = render(
        <MetricDiff
          {...defaultProps}
          className="custom-test-class"
        />
      )

      expect(container.firstChild).toHaveClass('custom-test-class')
    })

    it('handles edge case with very small differences', () => {
      render(
        <MetricDiff
          {...defaultProps}
          run1Score={0.999}
          run2Score={1.000}
          difference={0.001}
          percentageChange={0.1}
        />
      )

      expect(screen.getByText('99.9%')).toBeInTheDocument()
      expect(screen.getByText('100.0%')).toBeInTheDocument()
      expect(screen.getByText('+0.1pp')).toBeInTheDocument() // 0.001 * 100 = 0.1pp
    })

    it('handles large metric values correctly', () => {
      render(
        <MetricDiff
          {...defaultProps}
          run1Score={1234.567}
          run2Score={2345.678}
          difference={1111.111}
          percentageChange={90.0}
        />
      )

      expect(screen.getByText('1234.567')).toBeInTheDocument()
      expect(screen.getByText('2345.678')).toBeInTheDocument()
      expect(screen.getByText('+1111.111')).toBeInTheDocument()
      expect(screen.getByText('+90.0% change')).toBeInTheDocument()
    })
  })

  describe('Accessibility', () => {
    it('has proper semantic structure', () => {
      render(<MetricDiff {...defaultProps} />)

      // Check for heading structure
      expect(screen.getByRole('heading', { level: 4 })).toHaveTextContent('exact_match')
    })

    it('includes proper ARIA labels for statistical data', () => {
      render(
        <MetricDiff
          {...defaultProps}
          isSignificant={true}
          pValue={0.05}
        />
      )

      // The component should be accessible to screen readers
      const significantBadge = screen.getByText('Significant')
      expect(significantBadge).toBeInTheDocument()
    })
  })
})
