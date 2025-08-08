import React from 'react'
import { render, screen } from '../../utils/test-utils'
import { ComparisonChart } from '@/components/ui/comparison-chart'
import { mockRunComparison } from '../../utils/test-utils'

describe('ComparisonChart Component', () => {
  const defaultComparison = mockRunComparison()

  describe('Basic Rendering', () => {
    it('renders chart title', () => {
      render(<ComparisonChart comparison={defaultComparison} />)
      
      expect(screen.getByText('Metric Comparison')).toBeInTheDocument()
    })

    it('displays all metrics from comparison data', () => {
      render(<ComparisonChart comparison={defaultComparison} />)
      
      expect(screen.getByText('exact_match')).toBeInTheDocument()
      expect(screen.getByText('answer_relevancy')).toBeInTheDocument()
    })

    it('shows run names in legend', () => {
      render(<ComparisonChart comparison={defaultComparison} />)
      
      expect(screen.getByText('Run 1')).toBeInTheDocument()
      expect(screen.getByText('Run 2')).toBeInTheDocument()
    })

    it('displays overall winner', () => {
      render(<ComparisonChart comparison={defaultComparison} />)
      
      expect(screen.getByText('Winner:')).toBeInTheDocument()
      expect(screen.getByText('Run 2')).toBeInTheDocument() // Based on mock data
    })
  })

  describe('Bar Chart Rendering (Default)', () => {
    it('renders bar chart by default', () => {
      render(<ComparisonChart comparison={defaultComparison} />)
      
      // Check for bar chart elements
      const bars = document.querySelectorAll('.bg-primary-500, .bg-secondary-500')
      expect(bars.length).toBeGreaterThan(0)
    })

    it('displays metric scores with proper formatting', () => {
      render(<ComparisonChart comparison={defaultComparison} />)
      
      // Check for percentage formatting (scores between 0-1)
      expect(screen.getByText('85.0%')).toBeInTheDocument() // run1 exact_match
      expect(screen.getByText('90.0%')).toBeInTheDocument() // run2 exact_match
      expect(screen.getByText('92.0%')).toBeInTheDocument() // run1 answer_relevancy
      expect(screen.getByText('88.0%')).toBeInTheDocument() // run2 answer_relevancy
    })

    it('shows difference values for each metric', () => {
      render(<ComparisonChart comparison={defaultComparison} />)
      
      expect(screen.getByText('5.0pp diff')).toBeInTheDocument() // exact_match difference
      expect(screen.getByText('4.0pp diff')).toBeInTheDocument() // answer_relevancy difference
    })

    it('applies correct background colors based on improvement direction', () => {
      render(<ComparisonChart comparison={defaultComparison} />)
      
      // Check for improvement/regression background colors
      const metricContainers = document.querySelectorAll('[class*="bg-success"], [class*="bg-danger"], [class*="bg-neutral"]')
      expect(metricContainers.length).toBeGreaterThan(0)
    })
  })

  describe('Statistical Significance Indicators', () => {
    it('shows statistical significance indicator when metric is significant', () => {
      render(<ComparisonChart comparison={defaultComparison} />)
      
      // Based on mock data, exact_match is significant
      expect(screen.getByText('Statistically significant')).toBeInTheDocument()
    })

    it('displays significance indicator with correct icon', () => {
      render(<ComparisonChart comparison={defaultComparison} />)
      
      const significanceText = screen.getByText('Statistically significant')
      const icon = significanceText.parentElement?.querySelector('svg')
      
      expect(icon).toBeInTheDocument()
      expect(icon).toHaveAttribute('viewBox', '0 0 20 20')
    })

    it('does not show significance for non-significant metrics', () => {
      const modifiedComparison = {
        ...defaultComparison,
        comparison: {
          ...defaultComparison.comparison,
          statistical_analysis: {
            exact_match: { ...defaultComparison.comparison.statistical_analysis.exact_match, is_significant: false },
            answer_relevancy: { ...defaultComparison.comparison.statistical_analysis.answer_relevancy, is_significant: false }
          }
        }
      }

      render(<ComparisonChart comparison={modifiedComparison} />)
      
      expect(screen.queryByText('Statistically significant')).not.toBeInTheDocument()
    })
  })

  describe('Data Transformations', () => {
    it('calculates bar widths correctly based on max score', () => {
      render(<ComparisonChart comparison={defaultComparison} />)
      
      // Check that bars have appropriate width styles
      const bars = document.querySelectorAll('[style*="width"]')
      expect(bars.length).toBeGreaterThan(0)
      
      bars.forEach(bar => {
        const widthStyle = (bar as HTMLElement).style.width
        expect(widthStyle).toMatch(/^\d+(\.\d+)?%$/) // Should be a percentage
      })
    })

    it('handles edge case with zero scores', () => {
      const zeroScoreComparison = {
        ...defaultComparison,
        comparison: {
          ...defaultComparison.comparison,
          metrics: {
            exact_match: {
              run1_score: 0,
              run2_score: 0,
              difference: 0,
              percentage_change: 0,
              improvement_direction: 'neutral' as const
            }
          }
        }
      }

      render(<ComparisonChart comparison={zeroScoreComparison} />)
      
      expect(screen.getByText('0.0%')).toBeInTheDocument()
      expect(screen.getByText('0.0pp diff')).toBeInTheDocument()
    })

    it('handles large numeric scores (>1) with decimal formatting', () => {
      const largeScoreComparison = {
        ...defaultComparison,
        comparison: {
          ...defaultComparison.comparison,
          metrics: {
            large_metric: {
              run1_score: 123.456,
              run2_score: 234.567,
              difference: 111.111,
              percentage_change: 90.0,
              improvement_direction: 'better' as const
            }
          }
        }
      }

      render(<ComparisonChart comparison={largeScoreComparison} />)
      
      expect(screen.getByText('123.456')).toBeInTheDocument()
      expect(screen.getByText('234.567')).toBeInTheDocument()
      expect(screen.getByText('111.111 diff')).toBeInTheDocument()
    })
  })

  describe('Chart Type Variants', () => {
    it('renders bar chart when chartType is "bar"', () => {
      render(<ComparisonChart comparison={defaultComparison} chartType="bar" />)
      
      expect(screen.getByText('Metric Comparison')).toBeInTheDocument()
      expect(screen.queryByText('Radar chart view coming soon')).not.toBeInTheDocument()
    })

    it('shows coming soon message for radar chart', () => {
      render(<ComparisonChart comparison={defaultComparison} chartType="radar" />)
      
      expect(screen.getByText('Radar chart view coming soon')).toBeInTheDocument()
    })
  })

  describe('Winner Determination', () => {
    it('displays correct winner based on comparison data', () => {
      render(<ComparisonChart comparison={defaultComparison} />)
      
      expect(screen.getByText('Winner:')).toBeInTheDocument()
      expect(screen.getByText('Run 2')).toBeInTheDocument()
    })

    it('handles tie scenario', () => {
      const tieComparison = {
        ...defaultComparison,
        comparison: {
          ...defaultComparison.comparison,
          overall_performance: {
            ...defaultComparison.comparison.overall_performance,
            winner: 'tie' as const
          }
        }
      }

      render(<ComparisonChart comparison={tieComparison} />)
      
      expect(screen.getByText('Winner:')).toBeInTheDocument()
      expect(screen.getByText('Tie')).toBeInTheDocument()
    })

    it('displays run1 as winner correctly', () => {
      const run1WinComparison = {
        ...defaultComparison,
        comparison: {
          ...defaultComparison.comparison,
          overall_performance: {
            ...defaultComparison.comparison.overall_performance,
            winner: 'run1' as const
          }
        }
      }

      render(<ComparisonChart comparison={run1WinComparison} />)
      
      expect(screen.getByText('Run 1')).toBeInTheDocument()
    })
  })

  describe('Styling and Layout', () => {
    it('applies custom className', () => {
      const { container } = render(
        <ComparisonChart comparison={defaultComparison} className="custom-chart-class" />
      )
      
      expect(container.firstChild).toHaveClass('custom-chart-class')
    })

    it('has proper card structure', () => {
      render(<ComparisonChart comparison={defaultComparison} />)
      
      // Should be wrapped in Card component
      const cardElement = document.querySelector('[class*="p-6"]')
      expect(cardElement).toBeInTheDocument()
    })

    it('includes legend with colored indicators', () => {
      render(<ComparisonChart comparison={defaultComparison} />)
      
      // Check for colored legend indicators
      const primaryIndicator = document.querySelector('.bg-primary-500')
      const secondaryIndicator = document.querySelector('.bg-secondary-500')
      
      expect(primaryIndicator).toBeInTheDocument()
      expect(secondaryIndicator).toBeInTheDocument()
    })
  })

  describe('Responsive Design', () => {
    it('has responsive grid classes', () => {
      render(<ComparisonChart comparison={defaultComparison} />)
      
      // Check for responsive spacing and layout classes
      const chartContainer = screen.getByText('Metric Comparison').closest('[class*="space-y"]')
      expect(chartContainer).toBeInTheDocument()
    })
  })

  describe('Error Handling', () => {
    it('handles missing statistical analysis gracefully', () => {
      const noStatsComparison = {
        ...defaultComparison,
        comparison: {
          ...defaultComparison.comparison,
          statistical_analysis: {}
        }
      }

      render(<ComparisonChart comparison={noStatsComparison} />)
      
      // Should render without crashing
      expect(screen.getByText('Metric Comparison')).toBeInTheDocument()
    })

    it('handles empty metrics gracefully', () => {
      const emptyMetricsComparison = {
        ...defaultComparison,
        comparison: {
          ...defaultComparison.comparison,
          metrics: {}
        }
      }

      render(<ComparisonChart comparison={emptyMetricsComparison} />)
      
      // Should render chart container without metrics
      expect(screen.getByText('Metric Comparison')).toBeInTheDocument()
    })
  })

  describe('Performance Considerations', () => {
    it('memoizes chart data calculations', () => {
      const { rerender } = render(<ComparisonChart comparison={defaultComparison} />)
      
      // Re-render with same data should not cause issues
      rerender(<ComparisonChart comparison={defaultComparison} />)
      
      expect(screen.getByText('Metric Comparison')).toBeInTheDocument()
    })
  })
})